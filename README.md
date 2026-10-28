📈 FinVest — AI-Powered Trading & Portfolio Tracker

FinVest is a full-featured Streamlit web application designed for tracking personal stock portfolios, analyzing financial markets with real-time delayed data, and leveraging AI-driven insights for investment decision-making.

✨ Features

💼 Portfolio Overview: Track holdings across multiple custom portfolios, compute real-time market value, cost basis, unrealized/realized P&L, and monitor portfolio concentration risk.

📈 Live Market & Interactive Charts: Search global (US) and Indian (NSE/BSE) stocks via Yahoo Finance. View interactive candlestick and line price charts across multiple timeframes.

🤖 AI Stock Insights: Generate instant BUY / HOLD / SELL reports with confidence scores, risk levels, and actionable reasoning powered by Google Gemini.

💬 Conversational AI Chat: Ask market, strategy, or portfolio-related questions in English or natural Roman-script Hinglish.

⭐ Watchlist Management: Save favorite stocks and easily jump straight to market analysis.

🧾 Transaction Tracking: Log purchase and sale transactions with native dual-currency (USD/INR) conversion support.

🔐 Secure Authentication: User sign-up and login secured via PBKDF2 password hashing with backwards-compatible migration support.

🏗️ Project Architecture & File Structure

├── app.py           # Main application entry point & navigation routing
├── auth_view.py     # Authentication UI (Login & Sign Up)
├── portfolio.py    # Portfolio overview, holdings table & risk metrics
├── live_market.py  # Live stock search, interactive charts & trade panel
├── ai_insight.py   # Yahoo Finance data fetcher & Gemini AI report generator
├── ai_chat.py      # Conversational AI assistant & screener logic
├── watchlist.py    # Saved stocks and watchlist management
├── transactions.py # Trade execution & transaction history table
├── market_utils.py # Shared market helpers (FX conversion, symbol search)
├── theme.py        # Custom UI styling and CSS theme
├── db.py           # MySQL database connection layer
└── schema.sql      # Database initialization script


🛠️ Prerequisites & Setup

1. Database Configuration

Ensure you have access to a MySQL database (local instance or cloud provider like Aiven). Run your database setup script (or use the schema structure implied by db.py) to create the necessary tables: users, portfolios, stocks, watchlist, and transactions.

2. Environment Variables

Create a .env file in the root directory with the following contents:

# MySQL Database Credentials
DB_HOST=your-mysql-host
DB_USER=your-database-user
DB_PASSWORD=your-database-password
DB_PORT=25694
DB_NAME=finvest

# Google Gemini API Key
GOOGLE_API_KEY=your-google-gemini-api-key


3. Installation

Clone the repository and install the dependencies:

git clone https://github.com/your-username/finvest.git
cd finvest

# (Optional) Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required Python packages
pip install streamlit yfinance google-genai mysql-connector-python pandas plotly python-dotenv


🚀 Running the Application

Launch the Streamlit dashboard:

streamlit run app.py


Open your browser at http://localhost:8501.

⚠️ Disclaimer

FinVest is an educational project designed for research and portfolio tracking. AI-generated reports and market data are for informational purposes only and do not constitute financial advice.
