from flask import Flask, request, jsonify, Response
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
ARKESEL_SENDER_ID = "HAPPY HOME" # e.g., "HappyHome"

def init_db():
    """Set up the SQLite database, tables, and seed initial data."""
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    # Records table for attendance
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
    
    # Students table for global synchronization
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY,
            name TEXT,
            class_name TEXT,
            parent_phone TEXT
        )
    ''')
    
    # Pre-populate sample students if the table is empty
    cursor.execute('SELECT COUNT(*) FROM students')
    if cursor.fetchone()[0] == 0:
        sample_students = [
            ('s1', 'Kwame Mensah', 'Primary 1', '0240000001'),
            ('s2', 'Abena Osei', 'Primary 1', '0240000002'),
            ('s3', 'Kofi Annan', 'JHS 1', '0240000003'),
            ('s4', 'Ama Serwaa', 'JHS 1', '0240000004'),
            ('s5', 'Yaw Boadi', 'KG 2', '0240000005'),
            ('s6', 'Akua Nsiah', 'KG 2', '0240000006')
        ]
        cursor.executemany('INSERT INTO students (id, name, class_name, parent_phone) VALUES (?, ?, ?, ?)', sample_students)
        
    conn.commit()
    conn.close()

def send_sms(phone_number, student_name, date):
    """Dispatch SMS via Arkesel V2 API."""
    url = "https://sms.arkesel.com/api/v2/sms/send"
    message = f"Notice from Happy Home School: Your ward, {student_name}, was marked absent today ({date}). Please contact the school for any clarification."
    headers = {'api-key': ARKESEL_API_KEY, 'Content-Type': 'application/json'}
    payload = {"sender": ARKESEL_SENDER_ID, "message": message, "recipients": [phone_number]}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        print(f"SMS Status for {student_name}:", response.text)
    except Exception as e:
        print(f"Failed to send SMS to {phone_number}: {e}")

# --- NEW CLOUD STUDENT ROUTES ---
@app.route('/api/students', methods=['GET', 'POST'])
def handle_students():
    """Retrieve all students or save a new/updated student."""
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    if request.method == 'GET':
        cursor.execute('SELECT id, name, class_name, parent_phone FROM students')
        rows = cursor.fetchall()
        conn.close()
        students = [{"id": r[0], "name": r[1], "classId": r[2], "parentPhone": r[3]} for r in rows]
        return jsonify({"success": True, "data": students}), 200
        
    if request.method == 'POST':
        student = request.json
        cursor.execute('''
            INSERT OR REPLACE INTO students (id, name, class_name, parent_phone)
            VALUES (?, ?, ?, ?)
        ''', (student.get('id'), student.get('name'), student.get('classId'), student.get('parentPhone')))
        conn.commit()
        conn.close()
        return jsonify({"success": True}), 200

@app.route('/api/students/<student_id>', methods=['DELETE'])
def delete_student(student_id):
    """Remove a student from the cloud database."""
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM students WHERE id = ?', (student_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True}), 200
# --------------------------------

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
            cursor.execute('''
                INSERT INTO records (date, class_name, student_id, student_name, status, parent_phone)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (date, class_name, record.get('student_id'), record.get('student_name'), record.get('status'), record.get('parent_phone')))
            
            if record.get('status') == 'absent' and record.get('parent_phone'):
                send_sms(record.get('parent_phone'), record.get('student_name'), date)
                absent_count += 1
                
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": f"Data synced successfully. {absent_count} SMS notification(s) dispatched."}), 200

@app.route('/stats', methods=['GET'])
def get_stats():
    """Calculate attendance statistics for the dashboard."""
    try:
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        cursor.execute("SELECT class_name, status, COUNT(*) as count FROM records GROUP BY class_name, status")
        rows = cursor.fetchall()
        conn.close()
        
        stats_data = {}
        for row in rows:
            class_name = row[0]
            status = row[1].lower()
            count = row[2]
            if class_name not in stats_data:
                stats_data[class_name] = {'present': 0, 'absent': 0}
            if status in ['present', 'absent']:
                stats_data[class_name][status] = count
                
        return jsonify({"success": True, "data": stats_data}), 200
    except Exception as e:
        return jsonify({"success": False, "error": "Failed to load statistics"}), 500

@app.route('/top-absentees', methods=['GET'])
def get_top_absentees():
    """Find students with 2 or more absences."""
    try:
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT student_name, class_name, parent_phone, COUNT(*) as absences 
            FROM records WHERE status = 'absent' 
            GROUP BY student_name, class_name, parent_phone 
            HAVING absences >= 2 ORDER BY absences DESC
        ''')
        rows = cursor.fetchall()
        conn.close()
        absentees = [{"name": r[0], "class": r[1], "phone": r[2], "absences": r[3]} for r in rows]
        return jsonify({"success": True, "data": absentees}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/export', methods=['GET'])
def export_csv():
    """Export all database records to a downloadable CSV file."""
    try:
        conn = sqlite3.connect('attendance.db')
        cursor = conn.cursor()
        cursor.execute('SELECT date, class_name, student_name, status, parent_phone FROM records ORDER BY date DESC, class_name')
        rows = cursor.fetchall()
        conn.close()
        
        def generate():
            yield 'Date,Class,Student Name,Status,Parent Phone\n'
            for row in rows:
                yield f"{row[0]},{row[1]},{row[2]},{row[3]},{row[4]}\n"
                
        return Response(generate(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=attendance_report.csv'})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)