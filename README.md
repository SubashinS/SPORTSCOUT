# 🏃 SportScout — Setup Guide

A complete guide to get SportScout running on your machine from scratch.

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Clone the Repository](#clone-the-repository)
3. [Create a Firebase Project](#create-a-firebase-project)
4. [Enable Firestore Database](#enable-firestore-database)
5. [Generate a Service Account Key](#generate-a-service-account-key)
6. [Configure Environment Variables](#configure-environment-variables)
7. [Install Python Dependencies](#install-python-dependencies)
8. [Run the App](#run-the-app)
9. [Deploying to a Server](#deploying-to-a-server)
10. [Firestore Security Rules](#firestore-security-rules)
11. [Project Structure](#project-structure)
12. [Troubleshooting](#troubleshooting)

---

## 1. Prerequisites

Make sure you have the following installed before starting:

- **Python 3.9 or higher** — https://www.python.org/downloads/
- **pip** (comes with Python)
- **Git** — https://git-scm.com/downloads
- A **Google account** (to use Firebase)

To verify your Python installation, run:
```bash
python --version
```

---

## 2. Clone the Repository

```bash
git clone https://github.com/your-username/sportscout.git
cd sportscout
```

> Replace `your-username/sportscout` with the actual repository URL.

---

## 3. Create a Firebase Project

1. Go to [https://console.firebase.google.com](https://console.firebase.google.com)
2. Click **"Add project"**
3. Enter a project name (e.g. `sportscout-app`) and click **Continue**
4. Disable Google Analytics if you don't need it, then click **Create project**
5. Wait for the project to be created, then click **Continue**

---

## 4. Enable Firestore Database

1. In your Firebase project, click **"Firestore Database"** in the left sidebar
2. Click **"Create database"**
3. Choose **"Start in test mode"** for development *(you can secure it later — see [Firestore Security Rules](#firestore-security-rules))*
4. Select a Firestore location closest to you and click **Enable**

---

## 5. Generate a Service Account Key

This key allows the app to connect to your Firebase project securely.

1. In Firebase Console, click the ⚙️ **gear icon** (top left) → **Project settings**
2. Click the **"Service accounts"** tab
3. Make sure **"Firebase Admin SDK"** is selected
4. Click **"Generate new private key"**
5. Click **"Generate key"** in the popup
6. A `.json` file will be downloaded to your computer — this is your **service account key**

> ⚠️ **Keep this file secret. Never share it or upload it to GitHub.**

---

## 6. Configure Environment Variables

The app reads your Firebase credentials from an environment variable called `FIREBASE_CREDENTIALS`. This keeps your secret key out of the code.

### Step 1 — Open the downloaded `.json` key file

Open it in any text editor. It looks like this:

```json
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...",
  "client_email": "firebase-adminsdk-xxxxx@your-project.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  ...
}
```

### Step 2 — Create a `.env` file

In the root of the project folder, create a file called `.env` and add:

```
FIREBASE_CREDENTIALS={"type":"service_account","project_id":"your-project-id","private_key_id":"abc123","private_key":"-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n","client_email":"firebase-adminsdk@your-project.iam.gserviceaccount.com","client_id":"123456","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_x509_cert_url":"https://www.googleapis.com/robot/v1/metadata/x509/..."}
```

> Paste the **entire contents** of your `.json` file as a single line after `FIREBASE_CREDENTIALS=`

> ⚠️ The `.env` file is already listed in `.gitignore` — it will never be uploaded to GitHub.

### Step 3 — Set a secret key for Flask sessions (optional but recommended)

Also add this line to your `.env` file:

```
SPORTSCOUT_SECRET=any_long_random_string_you_make_up
```

You can generate one by running:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 7. Install Python Dependencies

### Create a virtual environment (recommended)

```bash
# Create virtual environment
python -m venv venv

# Activate it — Windows:
venv\Scripts\activate

# Activate it — Mac/Linux:
source venv/bin/activate
```

### Install required packages

```bash
pip install -r requirements.txt
```

If a `requirements.txt` is not present, install manually:

```bash
pip install flask
pip install firebase-admin
pip install werkzeug
pip install python-dotenv
pip install cryptography
pip install reportlab
```

---

## 8. Run the App

```bash
python app.py
```

You should see:
```
Firebase initialized successfully
 * Running on http://0.0.0.0:5000
```

Open your browser and go to: **http://localhost:5000**

### Register your first admin account

1. Go to `http://localhost:5000/register`
2. Fill in your details
3. Set **Role** to `admin`
4. Submit — you will be redirected to the admin dashboard

---

## 9. Deploying to a Server

If you want to host SportScout online (e.g. on Render, Railway, or a VPS), you need to set the environment variable on the server instead of using a `.env` file.

### Render

1. Go to your Render dashboard → your service → **Environment**
2. Click **Add Environment Variable**
3. Key: `FIREBASE_CREDENTIALS`
4. Value: paste the full JSON contents of your service account key file
5. Also add `SPORTSCOUT_SECRET` with a random string value
6. Click **Save** and redeploy

### Railway

1. Open your project → **Variables** tab
2. Click **New Variable**
3. Key: `FIREBASE_CREDENTIALS`, Value: full JSON contents
4. Also add `SPORTSCOUT_SECRET`
5. Railway will automatically redeploy

### VPS / Ubuntu Server

```bash
export FIREBASE_CREDENTIALS='{"type":"service_account",...}'
export SPORTSCOUT_SECRET='your_random_secret'
python app.py
```

To make these permanent, add them to your `~/.bashrc` or `~/.profile` file.

---

## 10. Firestore Security Rules

When you are ready to go live (not just testing), update your Firestore security rules to protect your data.

1. In Firebase Console → **Firestore Database** → **Rules** tab
2. Replace the default rules with:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // Users can only read and write their own data
    match /users/{userId} {
      allow read, write: if request.auth != null && request.auth.uid == userId;

      match /exercises/{exerciseId} {
        allow read, write: if request.auth != null && request.auth.uid == userId;
      }
    }
  }
}
```

3. Click **Publish**

> Note: The app uses Firebase Admin SDK (server-side), so these rules apply to client-side access only. The server always has full access via the service account key.

---

## 11. Project Structure

```
sportscout/
│
├── app.py                  # Main Flask application
├── .env                    # Your secret credentials (never commit this)
├── .gitignore              # Tells Git what to ignore
├── requirements.txt        # Python dependencies
├── events.json             # Events data file
│
├── templates/              # HTML templates
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── sai_dashboard.html
│   ├── leaderboard.html
│   ├── personal_dashboard.html
│   └── events.html
│
├── static/                 # CSS, JS, images
│
└── uploads/                # Temporary video uploads (auto-created)
```

---

## 12. Troubleshooting

### ❌ `Firebase initialization failed`
- Make sure `FIREBASE_CREDENTIALS` is set correctly in your `.env` file
- Check that the JSON is valid and on a single line
- Ensure `python-dotenv` is installed and `load_dotenv()` is called in `app.py`

### ❌ `ModuleNotFoundError: No module named 'firebase_admin'`
- Run `pip install firebase-admin`
- Make sure your virtual environment is activated

### ❌ `Permission denied` on Firestore
- Check your Firestore rules allow read/write in test mode
- Make sure the service account key belongs to the correct Firebase project

### ❌ App runs but database shows no data
- Make sure Firestore is enabled in your Firebase project (not Realtime Database)
- Check that you selected the right project when generating the service account key

### ❌ PDF export not working
- Run `pip install reportlab`

### ❌ Encryption features disabled warning
- Run `pip install cryptography`

---

## 🔒 Security Reminders

- **Never commit** `serviceAccountKey.json` or `.env` to GitHub
- **Regenerate your key** immediately if you accidentally push it to GitHub (Firebase Console → Project Settings → Service Accounts → Generate new key)
- Always use **strong passwords** for admin accounts
- Switch Firestore from **test mode** to **production rules** before going live

---

## 📬 Need Help?

If you run into issues not covered here, open an issue on the GitHub repository with:
- Your operating system
- Python version (`python --version`)
- The exact error message you see