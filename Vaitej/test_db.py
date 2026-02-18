import pymysql

# Replace 'YOUR_PASSWORD' with your actual RDS admin password
connection_params = {
    "host": "database-2.cw7ogqgaugzl.us-east-1.rds.amazonaws.com",
    "user": "admin",
    "password": "PASSWORD", 
    "port": 3306
}

try:
    conn = pymysql.connect(**connection_params)
    print("✅ SUCCESS: Your computer can connect to AWS RDS!")
    conn.close()
except Exception as e:
    print(f"❌ FAILED: Connection error. Reason: {e}")