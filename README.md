# CV Extractor

A web app that extracts structured data from PDF resumes using OpenAI and generates polished PDF CVs using LaTeX.

## Features

- Upload PDF resume → AI extracts structured data (personal info, education, skills, experience)
- Review and edit extracted fields in a web form
- Generate professionally formatted PDF using LaTeX
- Bilingual support (English/French) with auto-detection

## Quick Start

### Prerequisites

- Python 3.11+
- [Tectonic](https://tectonic-typesetting.github.io/) (LaTeX compiler)
- OpenAI API key

### Local Setup

```bash
# Install tectonic (macOS)
brew install tectonic

# Clone and setup
git clone <repo-url>
cd cv-extractor

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# Run
python smart_cv_app/app.py
```

Open http://localhost:5000

### Docker

```bash
# Build
docker build -t cv-extractor .

# Run
docker run -p 5000:5000 --env-file .env cv-extractor
```

> Note: Port 5000 may be used by macOS AirPlay. Use `-p 5001:5000` if needed.

## Project Structure

```
├── smart_cv_app/
│   └── app.py              # Flask backend
├── templates/
│   ├── index.html          # Frontend UI
│   └── cv_template.tex     # LaTeX template
├── static/uploads/         # Uploaded files + default photo
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Tech Stack

- **Backend**: Flask, OpenAI API (gpt-4o-mini), PyPDF2
- **PDF Generation**: Tectonic (LaTeX)
- **Frontend**: Vanilla HTML/CSS/JS

## License

MIT
