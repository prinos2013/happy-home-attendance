from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import requests
import datetime

app = Flask(__name__)

@app.route('/')
def home():
    return {"status": "online", "message": "Attendance API is running"}, 200

# Allow your frontend to communicate with this backend
CORS(app)

# Arkesel API Configuration
ARKESEL_API_KEY = "Q1lOWnlWbXdIWWZVT2ZwckdHSW0"
ARKESEL_SENDER_ID = "HAPPY HOME" # e.g., "HappyHome" (Max 11 characters)

def init_db():
    """Set up the SQLite database and create the attendance table."""
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            class_name TEXT,
            student_id TEXT,
            student_name TEXT,
            status TEXT,
            parent_phone TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def send_sms(phone_number, student_name, date):
    """Dispatch SMS via Arkesel V2 API."""
    url = "https://sms.arkesel.com/api/v2/sms/send"
    
    # Format message
    message = f"Notice from Happy Home School: Your ward, {student_name}, was marked absent today ({date}). Please contact the school for any clarification."
    
    headers = {
        'api-key': ARKESEL_API_KEY,
        'Content-Type': 'application/json'
    }
    
    payload = {
        "sender": ARKESEL_SENDER_ID,
        "message": message,
        "recipients": [phone_number]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        print(f"SMS Status for {student_name}:", response.text)
    except Exception as e:
        print(f"Failed to send SMS to {phone_number}: {e}")

@app.route('/sync', methods=['POST'])
def sync_attendance():
    """Receive data from frontend, save to database, and trigger SMS for absentees."""
    data = request.json
    attendance_data = data.get('attendance_data', [])
    
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    absent_count = 0
    
    for session in attendance_data:
        date = session.get('date')
        class_name = session.get('class_name')
        records = session.get('records', [])
        
        for record in records:
            # Insert into SQLite database
            cursor.execute('''
                INSERT INTO records (date, class_name, student_id, student_name, status, parent_phone)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (date, class_name, record.get('student_id'), record.get('student_name'), record.get('status'), record.get('parent_phone')))
            
            # Check if student is absent and has a phone number
            if record.get('status') == 'absent' and record.get('parent_phone'):
                send_sms(record.get('parent_phone'), record.get('student_name'), date)
                absent_count += 1
                
    conn.commit()
    conn.close()
    
    return jsonify({
        "status": "success", 
        "message": f"Data synced successfully. {absent_count} SMS notification(s) dispatched."
    }), 200

@app.route('/stats', methods=['GET'])
def get_stats():
    """Calculate attendance statistics for the dashboard."""
    try:
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        
        # Query the 'records' table to count present/absent per class
        cursor.execute('''
            SELECT class_name, status, COUNT(*) as count 
            FROM records 
            GROUP BY class_name, status
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        # Format the data into a dictionary for the frontend chart
        stats_data = {}
        for row in rows:
            class_name = row[0]
            status = row[1].lower()
            count = row[2]
            
            if class_name not in stats_data:
                stats_data[class_name] = {'present': 0, 'absent': 0}
            
            if status in ['present', 'absent']:
                stats_data[class_name][status] = count
                
        return jsonify({
            "success": True, 
            "data": stats_data
        }), 200

    except Exception as e:
        print("Error fetching stats:", e)
        return jsonify({"success": False, "error": "Failed to load statistics"}), 500

if __name__ == '__main__':
    init_db()
    # Run the server locally on port 5000
    app.run(debug=True, port=5000)