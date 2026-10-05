from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import sqlite3
import requests
import datetime
import os
import csv

def init_db():
    """Set up the SQLite database and seed initial data from the CSV file."""
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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY,
            name TEXT,
            class_name TEXT,
            parent_phone TEXT
        )
    ''')
    
    # Check if the database only has the default dummy students
    cursor.execute('SELECT COUNT(*) FROM students')
    if cursor.fetchone()[0] < 10:
        cursor.execute('DELETE FROM students') # Clear dummy data
        
        # Read and process the uploaded CSV file
        if os.path.exists('Renamed_Classes_Contacts.csv'):
            with open('Renamed_Classes_Contacts.csv', 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                students = []
                for i, row in enumerate(reader):
                    name = row.get('Name', '').strip()
                    if len(name) > 1:
                        # Standardize class formatting
                        cname = row.get('Class', '').strip().replace('JH ', 'JHS ')
                        if cname == 'Nursery2': cname = 'Nursery 2'
                        
                        # Standardize phone formatting (adding leading zeros)
                        phone = row.get('ParentPhone', '').strip()
                        if phone.endswith('.0'): phone = phone[:-2]
                        if len(phone) == 9: phone = '0' + phone
                        
                        students.append((f"stu_{i+1}", name, cname, phone))
                        
                if students:
                    cursor.executemany('INSERT INTO students (id, name, class_name, parent_phone) VALUES (?, ?, ?, ?)', students)
                    
    conn.commit()
    conn.close()

# Ensure database initializes when the cloud server boots
init_db()

app = Flask(__name__)

@app.route('/')
def home():
    return {"status": "online", "message": "Attendance API is running"}, 200

CORS(app)

ARKESEL_API_KEY = "Q1lOWnlWbXdIWWZVT2ZwckdHSW0"
ARKESEL_SENDER_ID = "HAPPY HOME"

def send_sms(phone_number, student_name, date):
    url = "https://sms.arkesel.com/api/v2/sms/send"
    message = f"Notice from Happy Home School: Your ward, {student_name}, was marked absent today ({date}). Please contact the school for any clarification."
    headers = {'api-key': ARKESEL_API_KEY, 'Content-Type': 'application/json'}
    payload = {"sender": ARKESEL_SENDER_ID, "message": message, "recipients": [phone_number]}
    try:
        response = requests.post(url, headers=headers, json=payload)
        print(f"SMS Status for {student_name}:", response.text)
    except Exception as e:
        print(f"Failed to send SMS to {phone_number}: {e}")

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

@app.route('/sync', methods=['POST'])
def sync_attendance():
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
        return jsonify({"success": False, "error": "Failed to load stats"}), 500

@app.route('/top-absentees', methods=['GET'])
def get_top_absentees():
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
    app.run(debug=True, port=5000)