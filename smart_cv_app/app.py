import os
import json
import subprocess
import jinja2
from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
from openai import OpenAI
from PyPDF2 import PdfReader
from dotenv import load_dotenv

# Resolve project paths relative to this file so Flask can find templates/static
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

# Load .env from project root so OPENAI_API_KEY is picked up
load_dotenv(os.path.join(BASE_DIR, '.env'))

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

# --- CONFIGURATION ---
UPLOAD_FOLDER = os.path.join(STATIC_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(os.path.dirname(__file__), 'output')
DEFAULT_PHOTO = os.path.relpath(os.path.join(STATIC_DIR, 'uploads', 'Picture1.jpg'), OUTPUT_FOLDER).replace('\\', '/')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# --- OPENAI API KEY ---
raw_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY")
if raw_key:
    raw_key = raw_key.strip().strip('"').strip("'")
OPENAI_API_KEY = raw_key
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY in your environment before running the app.")
client = OpenAI(api_key=OPENAI_API_KEY)

# --- JINJA2 LATEX SETUP ---
# We use custom delimiters to avoid clashing with LaTeX curly braces {}
latex_jinja_env = jinja2.Environment(
    block_start_string='\\BLOCK{',
    block_end_string='}',
    variable_start_string='\\VAR{',
    variable_end_string='}',
    comment_start_string='\\#{',
    comment_end_string='}',
    line_statement_prefix='%%',
    line_comment_prefix='%#',
    trim_blocks=True,
    autoescape=False,
    loader=jinja2.FileSystemLoader(BASE_DIR)
)

# --- LATEX ESCAPING HELPERS ---
LATEX_REPLACEMENTS = {
    '&': r'\&',
    '%': r'\%',
    '$': r'\$',
    '#': r'\#',
    '_': r'\_',
    '{': r'\{',
    '}': r'\}',
    '~': r'\textasciitilde{}',
    '^': r'\textasciicircum{}',
}

LIGATURE_MAP = {
    'œ': 'oe',
    'Œ': 'OE',
}

DASH_MAP = {
    '–': '--',
    '—': '--'
}

def latex_escape(text: str) -> str:
    if text is None:
        return ''
    s = str(text)
    # normalize dashes and ligatures
    for k, v in DASH_MAP.items():
        s = s.replace(k, v)
    for k, v in LIGATURE_MAP.items():
        s = s.replace(k, v)
    # normalize curly quotes to straight
    s = s.replace('’', "'").replace('“', '"').replace('”', '"').replace('‘', "'")
    for k, v in LATEX_REPLACEMENTS.items():
        s = s.replace(k, v)
    return s

def normalize_spacing(text: str) -> str:
    if text is None:
        return ''
    s = str(text)
    while '  ' in s:
        s = s.replace('  ', ' ')
    for token in ['-', '.', ',', '@']:
        s = s.replace(f' {token}', token).replace(f'{token} ', token)
    return s.strip()

def sanitize_data(obj):
    if isinstance(obj, dict):
        return {k: sanitize_data(v) if k != 'photo_path' else v for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_data(v) for v in obj]
    if isinstance(obj, str):
        return latex_escape(normalize_spacing(obj))
    return obj

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
    prompt = "Write a concise 2-3 sentence professional profile summary based on this CV. Language: " + ("English." if lang=='en' else "French.")
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

def polish_latex(tex: str, lang: str) -> str:
    if lang == 'en':
        instruction = """Review this LaTeX CV code and:
1. Translate ALL French text to English (section headers, content, everything)
2. Fix alignment and remove redundant blank lines
3. Ensure lists are compact
Respond with ONLY the complete LaTeX code."""
    else:
        instruction = """Review this LaTeX CV code and:
1. Keep all text in French
2. Fix alignment and remove redundant blank lines  
3. Ensure lists are compact
Respond with ONLY the complete LaTeX code."""
    
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": instruction},
            {"role": "user", "content": tex}
        ],
        temperature=0,
        max_tokens=4000
    )
    polished = completion.choices[0].message.content.strip()
    polished = polished.replace("```latex", "").replace("```", "").strip()
    return polished

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/parse-cv', methods=['POST'])
def parse_cv():
    """
    1. Saves the uploaded CV.
    2. Extracts text and sends to OpenAI to produce structured JSON.
    3. Returns JSON to frontend.
    """
    if 'cv_file' not in request.files:
        return jsonify({"error": "Missing CV file"}), 400

    cv_file = request.files['cv_file']

    # Save file to disk
    cv_filename = secure_filename(cv_file.filename)
    cv_path = os.path.join(UPLOAD_FOLDER, cv_filename)
    cv_file.save(cv_path)

    # --- Extract text from PDF ---
    try:
        reader = PdfReader(cv_path)
        raw_text = "\n".join([page.extract_text() or "" for page in reader.pages])
    except Exception as e:
        print(f"PDF Read Error: {e}")
        return jsonify({"error": "Could not read PDF text"}), 500

    # --- CALL OPENAI API ---
    try:
        target_lang = detect_language(raw_text)
        prompt = f"""
Extract data from this CV into this exact JSON structure. Respond in { 'English' if target_lang=='en' else 'French' } and translate content to that language if needed.
If a field is missing, use null. Do not shorten or summarize descriptions.
Structure:
{{
  "personal_info": {{ "name": "", "title": "", "email": "", "phone": "", "location": "", "summary": "" }},
  "education": [ {{ "period": "YYYY - YYYY", "degree": "", "school": "", "details": [""] }} ],
  "skills": ["skill1", "skill2"],
  "experience": [ {{ "period": "Month Year - Month Year", "role": "", "company": "", "details": [""] }} ]
}}
Return ONLY valid JSON.
"""

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You convert CV text into structured JSON."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "text", "text": "CV Text:\n" + raw_text[:100000]}
                    ]
                }
            ],
            temperature=0
        )

        json_str = completion.choices[0].message.content
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        extracted_data = json.loads(json_str)

        # Photo: use provided path if any, otherwise fall back to bundled Picture1.jpg
        extracted_data['personal_info']['photo_path'] = DEFAULT_PHOTO
        extracted_data['language'] = target_lang

        # Ensure summary exists; if missing, ask model to draft one
        if not extracted_data['personal_info'].get('summary'):
            try:
                extracted_data['personal_info']['summary'] = generate_summary(raw_text, extracted_data['language'])
            except Exception as _:
                extracted_data['personal_info']['summary'] = ''

        return jsonify(extracted_data)

    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    """
    1. Receives the Finalized JSON from Frontend.
    2. Renders LaTeX template.
    3. Compiles PDF.
    4. Sends PDF back to user.
    """
    data = request.json
    
    try:
        # Load Template
        template = latex_jinja_env.get_template('templates/cv_template.tex')

        # Enforce schema & sanitize/escape for LaTeX
        safe_data = sanitize_data(ensure_schema(data))
        lang = safe_data.get('language', 'fr')
        
        # Filter out empty entries
        safe_data['skills'] = [s for s in safe_data.get('skills', []) if s and s.strip()]
        safe_data['experience'] = [
            exp for exp in safe_data.get('experience', [])
            if (exp.get('role') and exp['role'].strip()) or (exp.get('company') and exp['company'].strip())
        ]
        safe_data['education'] = [
            edu for edu in safe_data.get('education', [])
            if (edu.get('degree') and edu['degree'].strip()) or (edu.get('school') and edu['school'].strip())
        ]
        # Filter empty details within entries
        for exp in safe_data['experience']:
            exp['details'] = [d for d in exp.get('details', []) if d and d.strip()]
        for edu in safe_data['education']:
            edu['details'] = [d for d in edu.get('details', []) if d and d.strip()]
        
        rendered_tex = template.render(
            personal_info=safe_data['personal_info'],
            education=safe_data['education'],
            skills=safe_data['skills'],
            experience=safe_data['experience'],
            lang=lang
        )

        # Final polish via LLM - also handles translation if English
        try:
            rendered_tex = polish_latex(rendered_tex, lang)
        except Exception as _:
            pass
        rendered_tex = rendered_tex.replace("```latex", "").replace("```", "").strip()
        
        # Save .tex file
        tex_path = os.path.join(OUTPUT_FOLDER, "generated_cv.tex")
        with open(tex_path, "w", encoding='utf-8') as f:
            f.write(rendered_tex)
            
        # Compile PDF using tectonic (lighter dependency than full TeX Live)
        # Tectonic auto-installs missing packages on first run.
        subprocess.run(
            [
                "tectonic",
                "-o",
                OUTPUT_FOLDER,
                "--keep-logs",
                tex_path,
            ],
            check=True,
        )
        
        pdf_path = os.path.join(OUTPUT_FOLDER, "generated_cv.pdf")
        return send_file(pdf_path, as_attachment=True)
        
    except Exception as e:
        print(f"PDF Gen Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
