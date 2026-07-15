import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    from routes.portfolio import portfolio_bp
    from routes.holdings import holdings_bp
    from routes.dividends import dividends_bp

    app.register_blueprint(portfolio_bp)
    app.register_blueprint(holdings_bp, url_prefix="/holdings")
    app.register_blueprint(dividends_bp, url_prefix="/dividends")

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)