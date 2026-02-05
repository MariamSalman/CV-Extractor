# CV Extractor

A web app that extracts structured data from PDF resumes using OpenAI and generates polished PDF CVs using LaTeX.

## Features

- Upload PDF resume → AI extracts structured data (personal info, education, skills, experience)
- Review and edit extracted fields in a web form
- Generate professionally formatted PDF using LaTeX
- Bilingual support (English/French) with auto-detection
- Password protection for secure access

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
# Edit .env and add your keys
```

Edit `.env`:
```
OPENAI_API_KEY=your-openai-api-key
APP_PASSWORD=your-secure-password
SECRET_KEY=generate-a-random-string
```

Run:
```bash
python smart_cv_app/app.py
```

Open http://localhost:5000

### Docker Compose (Recommended)

```bash
# Configure environment
cp .env.example .env
# Edit .env with your keys

# Build and run
docker compose up -d --build

# View logs
docker compose logs -f

# Stop
docker compose down
```

Open http://localhost:5001

> Note: Port 5000 may be used by macOS AirPlay. Docker Compose uses port 5001 by default.

## Production Deployment (Hetzner/VPS)

### 1. Server Setup

```bash
# Update system
apt update && apt upgrade -y
apt install -y curl git ufw fail2ban nginx

# Install Docker
curl -fsSL https://get.docker.com | sh
```

### 2. Configure Firewall

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

### 3. Configure Fail2Ban

```bash
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
banaction = ufw

[sshd]
enabled = true
port = 22
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 86400
EOF

systemctl enable fail2ban
systemctl restart fail2ban
```

### 4. Deploy Application

```bash
# Create app directory
mkdir -p /opt/cv-extractor && cd /opt/cv-extractor

# Upload files (from local machine)
# scp -r ./* root@YOUR_SERVER_IP:/opt/cv-extractor/

# Create .env
cat > .env << 'EOF'
OPENAI_API_KEY=your-openai-api-key
APP_PASSWORD=your-secure-password
SECRET_KEY=PLACEHOLDER
EOF

# Generate secret key
SECRET=$(openssl rand -hex 32)
sed -i "s/PLACEHOLDER/$SECRET/" .env

# Build and run
docker compose up -d --build
```

### 5. Configure Nginx Reverse Proxy

```bash
cat > /etc/nginx/sites-available/cv-extractor << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 20M;
    }
}
EOF

ln -sf /etc/nginx/sites-available/cv-extractor /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
```

### 6. (Optional) Add SSL with Let's Encrypt

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d your-domain.com
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key | Yes |
| `APP_PASSWORD` | Password to access the app | No (if empty, no auth) |
| `SECRET_KEY` | Flask session secret | No (auto-generated) |
| `FLASK_DEBUG` | Enable debug mode (`true`/`false`) | No |

## Project Structure

```
├── smart_cv_app/
│   ├── app.py              # Flask backend
│   └── output/             # Generated PDFs
├── templates/
│   ├── index.html          # Main UI
│   ├── login.html          # Login page
│   └── cv_template.tex     # LaTeX template
├── static/uploads/         # Uploaded files + default photo
├── docker-compose.yml      # Docker Compose config
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Tech Stack

- **Backend**: Flask, OpenAI API (gpt-4o-mini), PyPDF2
- **PDF Generation**: Tectonic (LaTeX)
- **Frontend**: Vanilla HTML/CSS/JS
- **Deployment**: Docker, Nginx, UFW, Fail2Ban

## Security Features

- Password-protected access
- UFW firewall (only SSH, HTTP, HTTPS)
- Fail2Ban for brute-force protection
- Nginx reverse proxy
- SSL/TLS support via Let's Encrypt
