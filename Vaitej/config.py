import os

class Config():
    # 1. Core App Security
    SECRET_KEY = os.environ.get("SECRET_KEY") or "super-key"
    
    # 2. AWS RDS Database
    # This uses your verified endpoint and user
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or \
        "mysql+pymysql://vaitej_user:PASSWORD@vaitej-db.ct4es2c28e73.ap-northeast-1.rds.amazonaws.com:3306/vaitej_ventures"
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 3. Gemini AI Configuration
    # Fallback removed for production security
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

    # 4. Cloudflare R2 Configuration (New)
    R2_BUCKET_NAME = "vaitej-uploads"
    R2_ACCESS_KEY = "62ca039cf8626a9e3ad6ad0be2ad8281"
    R2_SECRET_KEY = "c9c0bbd923a35cd9c69a95e0fadf4bc8a44fc5ff28ec2fc8de478e8a04ff6dd0"
    R2_ENDPOINT = "https://fb438de85aa1018a5636a0dc1f60770b.r2.cloudflarestorage.com"
    
    # Note: Replace this with your actual public R2.dev or Custom Domain URL
    R2_PUBLIC_DOMAIN = os.environ.get("R2_PUBLIC_DOMAIN") or "https://pub-your-id.r2.dev"