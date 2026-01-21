# 🚀 Vaitej Ventures  
### AI-Powered Founder–Investor Intelligence & Matching Platform  

Vaitej Ventures is a dual-sided fundraising intelligence platform engineered to bridge the gap between early-stage founders and venture investors.  
Unlike static directories, Vaitej Ventures uses **Google Gemini AI** to analyze pitch decks, simulate investor interviews, and generate high-signal compatibility scores.

---

## 🌟 Key Features  

### 👨‍💻 For Founders  
- **AI Pitch Deck Analyst**  
  Upload a PDF deck and receive instant analysis (score 0–100), strengths, weaknesses, and an “Investor Verdict”.

- **VC-Style Q&A Simulator**  
  Practice with a “Cynical VC” persona powered by Gemini to sharpen your pitch and identify weak spots.

- **Traction Dashboard**  
  Log monthly Revenue, Burn, Active Users → automatically compute **Runway**, **Burn Rate**, **Growth %**.

- **Investment Reports (Auto-Generated)**  
  Download structured HTML/JSON investment memos for investors.

---

### 💼 For Investors  
- **Smart Deal Feed**  
  Prioritized by Stage, Sector, Geography, Check Size fit.

- **Due Diligence Tools**  
  Add private notes, checklists, and improvement requests.

- **Portfolio Tracking**  
  Track MOIC, IRR, invested capital, and traction-backed performance.

- **Advanced Filters**  
  Stage • Sector • Geography • Traction thresholds.

---

### ⚡ Core Platform  
- **Real-Time Messaging** between matched founders and investors  
- **Verification System** for profiles  
- **Notifications** for matches, messages, traction changes  
- **Admin Panel** to verify users and manage platform activity  

---

## 🛠️ Tech Stack  

**Backend:** Python 3.x, Flask  
**Database:** MySQL + SQLAlchemy ORM  
**AI Engine:** Google Gemini Pro (`google-genai`)  
**Frontend:** HTML5, CSS3, JavaScript, Jinja2  
**Real-time:** Flask-SocketIO  
**Authentication:** Werkzeug Security (Session-based)

---

## ⚙️ Installation & Setup  

### **Prerequisites**  
- Python 3.8+  
- MySQL Server  
- Google Gemini API Key  

---

### **1. Clone the Repository**
```bash
git clone https://github.com/yourusername/vaitej-ventures.git
cd vaitej-ventures
```
2. Setup Virtual Environment
```bash
Copy code
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```
3. Install Dependencies
```bash
Copy code
pip install -r requirements.txt
```
4. Database Setup
Create database:
```sql
Copy code
CREATE DATABASE vaitej_ventures;
Import schema:
```
```bash
Copy code
mysql -u root -p vaitej_ventures < database/Vaitej_ventures_db.sql
```
5. Configure the Application
   
Edit config.py:

```python
Copy code
class Config():
    SECRET_KEY = "your-secret-key"
    SQLALCHEMY_DATABASE_URI = "mysql+pymysql://root:PASSWORD@localhost/vaitej_ventures"
    GEMINI_API_KEY = "your-gemini-api-key"
```
6. Run the Application
```bash
Copy code
python app.py
```
Visit:
👉 http://localhost:8000

📂 Project Structure
```Copy code
Vaitej-Ventures/
├── app.py                    # Main application entry
├── config.py                 # DB + API configuration
├── validators.py             # Form validation
├── database/
│   └── Vaitej_ventures_db.sql
├── static/
│   ├── css/
│   ├── js/
│   ├── images/
│   └── uploads/
├── templates/
│   ├── dashboard/
│   ├── admin/
│   └── auth/
└── README.md
```
🛣️ Roadmap (v2.1+)
🔧 In Progress
 Email Notifications (SMTP)

 Video Pitch Uploads (MP4 / Loom link)

 Stripe/Razorpay Payments

 Drag-and-Drop Kanban Deal Pipeline

 Portfolio Charts (Chart.js)

🔮 Planned
 Founder profile scoring

 Mobile App (Flutter/React Native)

 Deal Room (SAFE/SPA execution)

 Automated Term-Sheet Generator

📜 License
This project is licensed under the MIT License.
See LICENSE file for more details.

