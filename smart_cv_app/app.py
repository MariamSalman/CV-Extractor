import os
import json
import subprocess
import secrets
import copy
import threading
import uuid
from functools import wraps
from flask import Flask, request, jsonify, send_file, render_template, session, redirect, url_for
from werkzeug.utils import secure_filename
from openai import OpenAI
from PyPDF2 import PdfReader
from dotenv import load_dotenv
from docx import Document as DocxDocument
from docxtpl import DocxTemplate

# Resolve project paths relative to this file so Flask can find templates/static
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

# Load .env from project root so OPENAI_API_KEY is picked up
load_dotenv(os.path.join(BASE_DIR, '.env'))

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

# --- PASSWORD PROTECTION ---
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if APP_PASSWORD and not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- CONFIGURATION ---
UPLOAD_FOLDER = os.path.join(STATIC_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(os.path.dirname(__file__), 'output')
DEFAULT_PHOTO = os.path.join(STATIC_DIR, 'uploads', 'ntrace_logo.jpeg')
ALLOWED_EXTENSIONS = {'.pdf', '.doc', '.docx'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# --- ASYNC JOB STORAGE ---
# In-memory dict holding background job state.
# Each entry: {"status": "processing"|"done"|"error", "result": ..., "error": ...}
jobs: dict[str, dict] = {}

# --- ANONYMIZATION CONSTANTS ---
# Update COMPANY_PHONE in your .env file to match your company's phone number.
COMPANY_PHONE = os.getenv("COMPANY_PHONE", "+33 6 62 54 45 33")
COMPANY_EMAIL = "servicecommercial@ntrace-consulting.com"

# --- OPENAI API KEY ---
raw_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY")
if raw_key:
    raw_key = raw_key.strip().strip('"').strip("'")
OPENAI_API_KEY = raw_key
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY in your environment before running the app.")
client = OpenAI(api_key=OPENAI_API_KEY)

# --- LANGUAGE DETECTION ---
FRENCH_KEYWORDS = {
    'le', 'la', 'les', 'des', 'une', 'un', 'de', 'du', 'et', 'ou', 'avec', 'pour', 'sur', 'dans',
    'entreprise', 'compétences', 'expérience', 'formation', 'diplôme', 'poste', 'responsable',
    'gestion', 'développement', 'projet', 'équipe', 'année', 'années', 'mois', 'depuis',
    'janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre',
    'octobre', 'novembre', 'décembre', 'actuellement', 'présent'
}
ENGLISH_KEYWORDS = {
    'the', 'a', 'an', 'and', 'or', 'with', 'for', 'at', 'in', 'on', 'to', 'of',
    'experience', 'skills', 'education', 'summary', 'degree', 'position', 'manager',
    'development', 'project', 'team', 'year', 'years', 'month', 'months', 'since',
    'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september',
    'october', 'november', 'december', 'currently', 'present'
}

def detect_language(text: str) -> str:
    """Detect language based on keyword frequency."""
    words = set(text.lower().split())
    fr_score = len(words & FRENCH_KEYWORDS)
    en_score = len(words & ENGLISH_KEYWORDS)
    return 'en' if en_score > fr_score else 'fr'

def generate_summary(text: str, lang: str) -> str:
    prompt = "Write a concise 2-3 sentence professional profile summary based on this CV. Language: " + ("English." if lang == 'en' else "French.")
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You write concise CV summaries."},
            {"role": "user", "content": prompt + "\n\nCV Text:\n" + text[:8000]}
        ],
        temperature=0.3,
        max_tokens=180
    )
    return completion.choices[0].message.content.strip()

def ensure_schema(data):
    data = data or {}
    pi = data.get('personal_info', {})
    for key in ['name', 'title', 'email', 'phone', 'location', 'summary', 'photo_path']:
        if key == 'photo_path':
            pi.setdefault(key, DEFAULT_PHOTO)
        else:
            pi.setdefault(key, '')
    data['personal_info'] = pi
    data.setdefault('education', [])
    data.setdefault('skills', [])
    data.setdefault('experience', [])
    data.setdefault('language', 'fr')
    return data


# ──────────────────────────────────────────────
#  TEXT EXTRACTION  (PDF / DOCX / DOC)
# ──────────────────────────────────────────────

def extract_text(filepath: str) -> str:
    """Extract text from a CV file based on its extension."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.pdf':
        return _extract_pdf(filepath)
    elif ext == '.docx':
        return _extract_docx(filepath)
    elif ext == '.doc':
        return _extract_doc(filepath)
    else:
        raise ValueError(f"Unsupported file format: {ext}")

def _extract_pdf(filepath):
    reader = PdfReader(filepath)
    return "\n".join(page.extract_text() or "" for page in reader.pages)

def _extract_docx(filepath):
    doc = DocxDocument(filepath)
    parts = []
    for para in doc.paragraphs:
        parts.append(para.text)
    # Also grab text that lives inside tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)

def _extract_doc(filepath):
    """Extract text from legacy .doc files using antiword."""
    try:
        result = subprocess.run(
            ['antiword', filepath],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except FileNotFoundError:
        raise ValueError(
            "Cannot process .doc files: 'antiword' is not installed. "
            "Please convert your file to .docx or .pdf format."
        )
    except subprocess.CalledProcessError as e:
        raise ValueError(f"Error reading .doc file: {e.stderr}")


# ──────────────────────────────────────────────
#  ANONYMIZATION
# ──────────────────────────────────────────────

def anonymize_data(data):
    """Return an anonymized deep-copy of the CV data.

    Rules:
      - Name  → first-letter initials matching template format (e.g. "Fatima Jabari" → "F .J .")
      - Phone → company phone number
      - Email → company email address
    """
    anon = copy.deepcopy(data)
    pi = anon.get('personal_info', {})

    # Name → initials (template format: "M .G .")
    name = pi.get('name', '').strip()
    if name:
        parts = name.split()
        if len(parts) >= 2:
            pi['name'] = f"{parts[0][0].upper()} .{parts[-1][0].upper()} ."
        elif len(parts) == 1:
            pi['name'] = f"{parts[0][0].upper()} ."

    # Company contact info
    pi['phone'] = COMPANY_PHONE
    pi['email'] = COMPANY_EMAIL

    anon['personal_info'] = pi
    return anon


# ──────────────────────────────────────────────
#  WORD (.docx) DOCUMENT GENERATION
#  Uses docxtpl to fill CV_TEMPLATE.docx (a Jinja2-ready
#  version of the original template).  All formatting,
#  icons, text-boxes and layout are preserved automatically.
# ──────────────────────────────────────────────

TEMPLATE_PATH = os.path.join(BASE_DIR, 'cv_samples', 'CV_TEMPLATE.docx')


def build_cv_from_template(data, lang):
    """Build a CV by rendering CV_TEMPLATE.docx with docxtpl.

    The template uses two-column tables for education and experience,
    so each entry passes separate period/degree/school or period/role/company
    as plain strings.  Styling is handled by the template itself.
    """
    doc = DocxTemplate(TEMPLATE_PATH)
    pi = data['personal_info']

    # ── Education entries ─────────────────────
    edu_entries = []
    for edu in data.get('education', []):
        if not (edu.get('degree') or edu.get('school')):
            continue
        edu_entries.append({
            'period': edu.get('period', ''),
            'degree': edu.get('degree', ''),
            'school': edu.get('school', ''),
            'details': [d for d in edu.get('details', []) if d and d.strip()],
        })

    # ── Experience entries ────────────────────
    exp_entries = []
    for exp in data.get('experience', []):
        if not (exp.get('role') or exp.get('company')):
            continue
        exp_entries.append({
            'period': exp.get('period', ''),
            'role': exp.get('role', ''),
            'company': exp.get('company', ''),
            'details': [d for d in exp.get('details', []) if d and d.strip()],
        })

    # ── Skills ────────────────────────────────
    skills = [s for s in data.get('skills', []) if s and s.strip()]

    # ── Build context ─────────────────────────
    context = {
        'name':       pi.get('name', ''),
        'title':      (pi.get('title') or '').upper(),
        'email':      pi.get('email', ''),
        'phone':      pi.get('phone', ''),
        'location':   pi.get('location', ''),
        'summary':    pi.get('summary', ''),
        # Section headings
        'education_title':  ('FORMATION - CERTIFICATION'
                             if lang != 'en' else 'EDUCATION - CERTIFICATION'),
        'skills_title':     'COMPETENCES' if lang != 'en' else 'SKILLS',
        'experience_title': ('EXPÉRIENCES PROFESSIONNELLES'
                             if lang != 'en' else 'PROFESSIONAL EXPERIENCE'),
        # Section data
        'education':  edu_entries,
        'skills':     skills,
        'experience': exp_entries,
    }

    doc.render(context)
    return doc


# ──────────────────────────────────────────────
#  ROUTES
# ──────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not APP_PASSWORD:
        return redirect(url_for('index'))
    error = None
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == APP_PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('index'))
        error = 'Invalid password'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

EXTRACTION_PROMPT = """\
Extract data from this CV into the JSON structure below. \
Respond in {lang_instruction} and translate content to that language if needed.
If a field is missing, use null. Do not shorten or summarize descriptions.

Rules:
- For "skills": respect the original structure of the CV. If skills are grouped \
together on one line or under a category, keep them as a single item. Do not \
break apart what the CV presents as one logical entry.
- For all arrays: preserve the level of detail from the original. Do not split \
one sentence into multiple items, and do not merge separate entries into one.

Structure:
{{
  "personal_info": {{ "name": "", "title": "", "email": "", "phone": "", "location": "", "summary": "" }},
  "education": [ {{ "period": "YYYY - YYYY", "degree": "", "school": "", "details": [""] }} ],
  "skills": ["skill or skill group 1", "skill or skill group 2"],
  "experience": [ {{ "period": "Month Year - Month Year", "role": "", "company": "", "details": [""] }} ]
}}
Return ONLY valid JSON.
"""


def _call_openai_text(raw_text: str, target_lang: str) -> dict:
    """Send extracted text to GPT-4o-mini and return structured CV data."""
    lang_instruction = 'English' if target_lang == 'en' else 'French'
    prompt = EXTRACTION_PROMPT.format(lang_instruction=lang_instruction)

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You convert CV text into structured JSON."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "text", "text": "CV Text:\n" + raw_text[:100000]},
                ],
            },
        ],
        temperature=0,
    )
    json_str = completion.choices[0].message.content
    json_str = json_str.replace("```json", "").replace("```", "").strip()
    return json.loads(json_str)


# ──────────────────────────────────────────────
#  CV ANALYSIS  (second LLM call)
# ──────────────────────────────────────────────

ANALYSIS_PROMPT = """\
You are an expert CV reviewer. Analyse the following structured CV data and \
return a JSON object with exactly these keys:

1. "candidate_overview" — a concise 2-3 sentence overview of the candidate \
for the reviewer's reference (who they are, their main expertise, \
years/level of experience). This is NOT the same as the CV's "summary" field. \
Write in {lang_instruction}.

2. "missing_fields" — a list of field names that are empty, null, or missing. \
Check these fields: name, title, email, phone, location, summary, education, \
skills, experience. Only list the ones that are actually missing or empty.

3. "suggestions" — an array of objects, one per missing or empty field for \
which you can propose useful content. Each object must have:
  - "field": the field name (e.g. "title", "summary", "location", "skills")
  - "label": a short human-readable label for what this field is \
(e.g. "Professional Title", "Profile Summary"). Write in {lang_instruction}.
  - "value": your proposed content for that field. For text fields provide a \
string. For "skills" provide a comma-separated string of skills.
IMPORTANT: if the CV's "summary" field in personal_info is empty, you MUST \
include a suggestion for it. The suggested summary should be a 1-2 line \
professional profile description. Do NOT mention the candidate's name in it. \
Focus on their expertise, role, and key strengths.
Only include suggestions where you can infer reasonable content from the rest \
of the CV. If nothing is missing or you cannot infer a value, return an empty list.

4. "compact_skills" — look at the "skills" array. If the skills are already \
compact (short phrases, keyword-style entries like "Python", "Project Management", \
"Docker, Kubernetes"), set this to null. But if any skill entry is a long \
sentence or paragraph (more than ~8 words), rewrite ALL the skills as a clean, \
compact, professional keyword-style list. Group related skills logically. \
Write in {lang_instruction}. If null, omit the key or set to null.

CV Data:
{cv_json}

Return ONLY valid JSON matching the structure above.
"""


def _call_openai_analysis(cv_data: dict, target_lang: str) -> dict:
    """Analyse extracted CV data and return summary, missing fields,
    suggestions, and optionally compact skills."""
    lang_instruction = 'English' if target_lang == 'en' else 'French'
    # Remove photo_path from data sent to LLM (not useful for analysis)
    send_data = copy.deepcopy(cv_data)
    send_data.get('personal_info', {}).pop('photo_path', None)

    prompt = ANALYSIS_PROMPT.format(
        lang_instruction=lang_instruction,
        cv_json=json.dumps(send_data, ensure_ascii=False, indent=2),
    )

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a professional CV reviewer. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    json_str = completion.choices[0].message.content
    json_str = json_str.replace("```json", "").replace("```", "").strip()
    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        result = {"candidate_overview": "", "missing_fields": [], "suggestions": [], "compact_skills": None}

    # Normalise keys
    result.setdefault("candidate_overview", "")
    result.setdefault("missing_fields", [])
    result.setdefault("suggestions", [])
    result.setdefault("compact_skills", None)
    return result


def _process_cv_job(job_id: str, cv_path: str, ext: str):
    """Background worker: runs extraction + analysis and stores result in jobs dict."""
    try:
        raw_text = extract_text(cv_path)
        target_lang = detect_language(raw_text)
        extracted_data = _call_openai_text(raw_text, target_lang)

        # Photo: use default bundled photo
        extracted_data['personal_info']['photo_path'] = DEFAULT_PHOTO
        extracted_data['language'] = target_lang

        # If summary is missing, leave it empty — the analysis call
        # will flag it as a missing field and suggest content the user
        # can accept or dismiss.
        if not extracted_data['personal_info'].get('summary'):
            extracted_data['personal_info']['summary'] = ''

        # ── Second LLM call: CV analysis ──────────────
        try:
            analysis = _call_openai_analysis(extracted_data, target_lang)
        except Exception as e:
            print(f"Analysis call failed (non-fatal): {e}")
            analysis = {
                "summary": "",
                "missing_fields": [],
                "suggestions": [],
                "compact_skills": None,
            }

        extracted_data['analysis'] = analysis
        jobs[job_id] = {"status": "done", "result": extracted_data}

    except Exception as e:
        print(f"CV Parse Error (job {job_id}): {e}")
        jobs[job_id] = {"status": "error", "error": str(e)}


@app.route('/parse-cv', methods=['POST'])
@login_required
def parse_cv():
    """Upload a CV, validate it, kick off background processing, return job_id.

    The actual LLM calls run in a background thread so the HTTP response
    returns immediately (avoids platform proxy timeouts).
    Poll GET /job-status/<job_id> for results.
    """
    if 'cv_file' not in request.files:
        return jsonify({"error": "Missing CV file"}), 400

    cv_file = request.files['cv_file']
    cv_filename = secure_filename(cv_file.filename)
    ext = os.path.splitext(cv_filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({
            "error": f"Unsupported format '{ext}'. Please upload a PDF, DOC, or DOCX file."
        }), 400

    cv_path = os.path.join(UPLOAD_FOLDER, cv_filename)
    cv_file.save(cv_path)

    job_id = uuid.uuid4().hex
    jobs[job_id] = {"status": "processing"}

    thread = threading.Thread(
        target=_process_cv_job,
        args=(job_id, cv_path, ext),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id}), 202


@app.route('/job-status/<job_id>')
@login_required
def job_status(job_id):
    """Poll this endpoint to get background job results."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job["status"] == "done":
        result = job["result"]
        del jobs[job_id]  # cleanup
        return jsonify({"status": "done", "result": result})

    if job["status"] == "error":
        err = job["error"]
        del jobs[job_id]  # cleanup
        return jsonify({"status": "error", "error": err}), 500

    return jsonify({"status": "processing"})


@app.route('/generate-docx', methods=['POST'])
@login_required
def generate_docx():
    """Receive final JSON, anonymize, build Word document, return .docx."""
    data = request.json

    try:
        data = ensure_schema(data)
        lang = data.get('language', 'fr')

        # Filter empty entries
        data['skills'] = [s for s in data.get('skills', []) if s and s.strip()]
        data['experience'] = [
            exp for exp in data.get('experience', [])
            if (exp.get('role') and exp['role'].strip()) or (exp.get('company') and exp['company'].strip())
        ]
        data['education'] = [
            edu for edu in data.get('education', [])
            if (edu.get('degree') and edu['degree'].strip()) or (edu.get('school') and edu['school'].strip())
        ]
        for exp in data['experience']:
            exp['details'] = [d for d in exp.get('details', []) if d and d.strip()]
        for edu in data['education']:
            edu['details'] = [d for d in edu.get('details', []) if d and d.strip()]

        # Anonymize personal info for the output document
        anon_data = anonymize_data(data)

        # Build Word document from template
        doc = build_cv_from_template(anon_data, lang)

        # Derive filename from anonymized initials
        anon_name = anon_data['personal_info'].get('name', 'CV')
        clean_name = ''.join(c for c in anon_name if c.isalnum() or c in (' ', '_')).strip().replace(' ', '_')
        filename = f"CV_{clean_name}.docx" if clean_name else "generated_cv.docx"

        docx_path = os.path.join(OUTPUT_FOLDER, "generated_cv.docx")
        doc.save(docx_path)

        return send_file(docx_path, as_attachment=True, download_name=filename)

    except Exception as e:
        print(f"DOCX Gen Error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
