import hmac
import hashlib
import streamlit as st
from db import run_query


# ---------- PASSWORD HASHING (same scheme as before, existing users keep working) ----------

def hash_password(password):
    salt = "finvest_local_password_salt"
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000
    ).hex()


def verify_password(password, stored_password):
    if not stored_password:
        return False

    stored = str(stored_password)

    # Current format
    if hmac.compare_digest(stored, hash_password(password)):
        return True

    # Older SHA-256 hashes (migration support)
    old_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(stored, old_hash)


AUTH_CSS = """
<style>
.fv-auth-brand{ text-align:center; margin:6vh 0 1.2rem; }
.fv-auth-brand .logo{
  display:inline-flex; align-items:center; justify-content:center;
  width:64px; height:64px; border-radius:20px; font-size:2rem;
  background:linear-gradient(135deg,#4F7BFF,#2DD4A0);
  box-shadow:0 12px 40px rgba(79,123,255,.35);
}
.fv-auth-brand h1{ margin:14px 0 4px; font-size:2.3rem; font-weight:800; letter-spacing:-1px; }
.fv-auth-brand p{ color:#8B9AB5; margin:0; }
.fv-auth-points{ display:flex; justify-content:center; gap:10px; flex-wrap:wrap; margin:16px 0 8px; }
.fv-auth-points span{
  padding:5px 12px; border-radius:999px; font-size:.8rem; color:#8B9AB5;
  background:rgba(22,32,56,.85); border:1px solid #1F2C45;
}
div[data-testid="stForm"]{
  background:rgba(16,24,43,.78); border:1px solid #1F2C45; border-radius:20px; padding:24px;
}
</style>
"""


def _first(row):
    """Accept list results from run_query."""
    if isinstance(row, list):
        return row[0] if row else None
    return row


# ---------- AUTH PAGE ----------

def render_auth():
    st.markdown(AUTH_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="fv-auth-brand">'
        '<div class="logo">📈</div>'
        '<h1>FinVest</h1>'
        '<p>AI-powered investing and risk management</p>'
        '<div class="fv-auth-points">'
        '<span>Live market data</span><span>AI Buy / Hold / Sell reports</span>'
        '<span>Portfolio risk check</span></div></div>',
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([1, 1.4, 1])

    with center:
        login_tab, signup_tab = st.tabs(["🔐 Login", "✨ Sign Up"])

        # ---------- LOGIN ----------
        with login_tab:
            with st.form("login_form"):
                email = st.text_input("Email", placeholder="you@example.com").strip().lower()
                password = st.text_input("Password", type="password")
                login_clicked = st.form_submit_button(
                    "Login", type="primary", use_container_width=True
                )

            if login_clicked:
                if not email or not password:
                    st.warning("Please enter your email and password.")
                else:
                    try:
                        user = _first(run_query(
                            """
                            SELECT user_id, name, email, pass_word
                            FROM users
                            WHERE email = %s
                            LIMIT 1
                            """,
                            (email,),
                            fetchone=True,
                        ))

                        if not user:
                            st.error("No account found for this email. Check it or create an account.")
                        else:
                            if isinstance(user, dict):
                                user_id = user["user_id"]
                                name = user["name"]
                                user_email = user["email"]
                                saved_password = str(user["pass_word"])
                            else:
                                user_id, name, user_email, saved_password = user

                            if verify_password(password, saved_password):
                                st.session_state["user_id"] = user_id
                                st.session_state["user_name"] = name
                                st.session_state["user_email"] = user_email
                                st.session_state["authenticated"] = True
                                st.rerun()
                            else:
                                st.error("Incorrect email or password.")

                    except Exception as e:
                        st.error("Login failed. Database error:")
                        st.code(str(e))

        # ---------- SIGN UP ----------
        with signup_tab:
            with st.form("signup_form"):
                name = st.text_input("Full name")
                email = st.text_input("Email address", key="signup_email").strip().lower()
                password = st.text_input("Create password", type="password",
                                         help="At least 8 characters")
                confirm = st.text_input("Confirm password", type="password")
                signup_clicked = st.form_submit_button(
                    "Create account", type="primary", use_container_width=True
                )

            if signup_clicked:
                if not name.strip() or not email or not password:
                    st.warning("Please complete all fields.")
                elif password != confirm:
                    st.error("Passwords do not match.")
                elif len(password) < 8:
                    st.error("Use a password with at least 8 characters.")
                else:
                    try:
                        existing = _first(run_query(
                            "SELECT user_id FROM users WHERE email = %s LIMIT 1",
                            (email,),
                            fetchone=True,
                        ))

                        if existing:
                            st.warning("This email is already registered. Use the Login tab.")
                        else:
                            run_query(
                                "INSERT INTO users (name, email, pass_word) VALUES (%s, %s, %s)",
                                (name.strip(), email, hash_password(password)),
                            )
                            st.success("Account created! Go to the Login tab to sign in.")

                    except Exception as e:
                        st.error("Sign up failed. Database error:")
                        st.code(str(e))


# Support both function names used by different app.py versions.
def show_auth():
    return render_auth()