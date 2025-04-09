# Project Setup Guide

## Prerequisites

-   Python (recommended version: 3.10.x or later)
-   pip
-   git

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/S-FX-com/ObieDesk-Backend.git
cd ObieDesk-Backend
```

### 2. Create Virtual Environment

```bash
python -m venv venv
```

### 3. Activate Virtual Environment

#### On Windows

```bash
venv\Scripts\activate
```

#### On macOS/Linux

```bash
source venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables

```bash
cp .env.example .env
```

Edit the `.env` file and set your required variables

### 6. Initialize Database

```bash
python init_db.py
```

### 7. Start Development Server

```bash
uvicorn app.main:app --reload
```

## Useful Commands

### Deactivate Virtual Environment

```bash
deactivate
```

## Troubleshooting

-   Ensure Python 3.10.x or later is installed
-   Verify you're inside the virtual environment before installing dependencies
-   Check that all environment variables are configured correctly

## Project Structure

```
project/
│
├── venv/               # Virtual environment
├── app/                # Application source code
├── .env                # Environment variables (do not commit)
├── .env.example        # Example environment variables
├── requirements.txt    # Project dependencies
└── init_db.py          # Database initialization script
```

## Additional Notes

-   Keep your virtual environment activated while working on the project
-   Update `requirements.txt` when adding new dependencies using `pip freeze > requirements.txt`
