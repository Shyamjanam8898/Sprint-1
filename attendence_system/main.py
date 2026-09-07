
import random
from flask import Flask, render_template, request, session, redirect, url_for, flash, jsonify, make_response
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import BigInteger
from functools import wraps
import json
import pymysql
pymysql.install_as_MySQLdb()
import datetime
from sqlalchemy import func, text
import io, csv
from sqlalchemy.exc import OperationalError
import os, base64
import secrets, string
import datetime


with open("config.json" , 'r') as con:
    parameters = json.load(con)["parameters"]
local_server  = True

app = Flask(__name__)
app.secret_key = parameters['secret_key']
if local_server:
    app.config["SQLALCHEMY_DATABASE_URI"] = parameters['local_uri']
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = parameters['prod_uri']
db=SQLAlchemy(app)


def login_required(f):
    """Decorator to require login for a route. Redirects to login if user not in session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/")
@login_required
def home():
    print("Fetching student data...")
    students = Student_reg.query.all()
    print(f"Found {len(students)} students.")
    return render_template("home.html", students=students)

@app.route("/search", methods=["GET"])
@login_required
def search():
    query = request.args.get("q", "")
    students = []
    if query:
        students = Student_reg.query.filter(Student_reg.Student_name.ilike(f"%{query}%")).all()
    return render_template("home.html", students=students, parameters=parameters)


@app.route('/api/search_students')
@login_required
def api_search_students():
    q = request.args.get('q', '').strip()
    standard_filter = request.args.get('standard', '').strip()
    # simple server-side search: match name or number or standard
    query = Student_reg.query
    if standard_filter:
        # restrict to specific class/batch when provided
        query = query.filter(Student_reg.Standard == standard_filter)

    if q:
        like_q = f"%{q}%"
        query = query.filter(
            (Student_reg.Student_name.ilike(like_q)) |
            (Student_reg.Student_number.ilike(like_q)) |
            (Student_reg.Standard.ilike(like_q))
        )

    # return a reasonable number when query is empty
    results = query.limit(200).all()

    students = []
    for s in results:
        photo = s.Student_photo if s.Student_photo else 'placeholder.png'
        photo_url = url_for('static', filename=f'uploads/{photo}')
        students.append({
            'Sr_no': s.Sr_no,
            'Student_id': s.Student_id,
            'Student_name': s.Student_name,
            'Student_number': s.Student_number,
            'Standard': s.Standard,
            'Student_photo': photo,
            'photo_url': photo_url,
            'DOA': s.DOA,
        })

    return jsonify({'students': students})


class Notification(db.Model):
    Date = db.Column(db.String(12),unique=False,nullable=False)
    Sr_no = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    Message = db.Column(db.String(100), nullable=False)
    # optional attached filename saved in uploads folder
    Attachment = db.Column(db.String(200), unique=False, nullable=True)
    # Target: 'ALL' or Standard string (e.g. '10th') or NULL
    Target = db.Column(db.String(40), unique=False, nullable=True)
    Created_by = db.Column(db.String(80), unique=False, nullable=True)


@app.route("/Notification", methods=['GET', 'POST'])
@login_required
def notification():
    # Provide list of Standards for the selector
    Standards = db.session.query(Student_reg.Standard).distinct().all()
    classes = [s[0] for s in Standards]

    success = False
    error = None
    if request.method == 'POST':
        Message = request.form.get('Message')
        target = request.form.get('target')  # 'ALL' or standard
        all_classes = request.form.get('all_classes')
        # file upload field
        attachment_file = request.files.get('attachment')
        # If 'all_classes' checkbox set, treat as ALL
        if all_classes:
            target = 'ALL'

        if not Message or not Message.strip():
            error = 'Message cannot be empty.'
            return render_template('Notification.html', parameters=parameters, classes=classes, error=error)

        filename = None
        # process file upload if present
        if attachment_file and attachment_file.filename:
            if allowed_file(attachment_file.filename):
                filename = secure_filename(attachment_file.filename)
                try:
                    attachment_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                except Exception as e:
                    print('Failed to save attachment:', e)
                    error = 'Failed to upload attachment.'
                    return render_template('Notification.html', parameters=parameters, classes=classes, error=error)
            else:
                error = 'File type not allowed.'
                return render_template('Notification.html', parameters=parameters, classes=classes, error=error)

        try:
            entry = Notification(
                Message=Message.strip(),
                Date=datetime.datetime.now().strftime('%Y-%m-%d'),
                Attachment=filename,
                Target=(target or None),
                Created_by=session.get('user')
            )
            db.session.add(entry)
            db.session.commit()
            success = True
        except Exception as e:
            db.session.rollback()
            error = 'Failed to post notice.'
            print('Failed to create notification:', e)

    return render_template("Notification.html", parameters=parameters, classes=classes, success=success, error=error)

@app.route('/student_notifications')
@login_required
def student_notifications():
    # If role must be student-only, you can enforce it:
    # if session.get('role') != 'student': abort(403)
    student = None
    if session.get('role') == 'student':
        student = Student_reg.query.filter_by(Student_id=session.get('user')).first()
        if student:
            # Show notifications targeted to ALL, to this student's Standard, or with NULL target (legacy)
            notifications = Notification.query.filter(
                (Notification.Target == 'ALL') | (Notification.Target == student.Standard) | (Notification.Target == None)
            ).order_by(Notification.Sr_no.desc()).all()
        else:
            notifications = Notification.query.order_by(Notification.Sr_no.desc()).all()
    else:
        # Non-students (admins/root) see all notifications
        notifications = Notification.query.order_by(Notification.Sr_no.desc()).all()

    return render_template('Student_notification.html', notifications=notifications, student=student, parameters=parameters)

class Student_reg(db.Model):
    Sr_no = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    Student_name = db.Column(db.String(80), unique=False, nullable=False)
    Father_name = db.Column(db.String(80), unique=False, nullable=False)
    Mother_name = db.Column(db.String(80), unique=False, nullable=False)
    Student_number = db.Column(db.BigInteger, unique=False, nullable=False)
    Parent_number = db.Column(db.Integer, unique=False, nullable=False)
    Address = db.Column(db.String(120), unique=False, nullable=False)
    DOB = db.Column(db.String(12), unique=False, nullable=False)
    Gender = db.Column(db.String(10), unique=False, nullable=False)
    Student_photo= db.Column(db.String(100), unique=False, nullable=False)
    Student_id= db.Column(db.String(64), unique=True, nullable=False)
    Student_password = db.Column(db.String(64), unique=False, nullable=False)
    Student_batch = db.Column(db.String(80), unique=False, nullable=True)
    Stream = db.Column(db.String(40), unique=False, nullable=True)
    Standard = db.Column(db.String(12), unique=False, nullable=False)
    School_name = db.Column(db.String(80), unique=False, nullable=False)
    Mother_profession = db.Column(db.String(80), unique=False, nullable=False)
    Father_profession = db.Column(db.String(80), unique=False, nullable=False)
    DOA=db.Column(db.Date, unique=False, nullable=False)
    # Optional metadata about who created the student and when
    Added_by = db.Column(db.String(80), unique=False, nullable=True)
    Created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    Admin_id = db.Column(db.String(64), unique=True, nullable=False)
    Password=db.Column(db.String(128), unique=False, nullable=False)
    Name = db.Column(db.String(120), unique=False, nullable=False)
    Email = db.Column(db.String(120), unique=False, nullable=True)
    Phone = db.Column(db.String(32), unique=False, nullable=True)
    Photo = db.Column(db.String(100), unique=False, nullable=True)
    Created_at = db.Column(db.DateTime, default=datetime.datetime.now)


class Batch(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    name = db.Column(db.String(80), unique=False, nullable=False)
    Standard = db.Column(db.String(12), unique=False, nullable=False)
    Stream = db.Column(db.String(40), unique=False, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)


class Login(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    account_id = db.Column(db.String(128), unique=False, nullable=False)
    password = db.Column(db.String(128), unique=False, nullable=False)
    role = db.Column(db.String(20), unique=False, nullable=False)  # 'admin' | 'student'
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    last_login = db.Column(db.DateTime, nullable=True)


UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# allow common document/image file types for attachments
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/Student_reg', methods=['GET', 'POST'])
@login_required
def register():
    # Prepare select lists for template
    standards = ['1st','2nd','3rd','4th','5th','6th','7th','8th','9th','10th','11th','12th']
    streams = ['Science','Commerce','Arts']

    # Ensure default batches exist for 11th/12th (admin/root can modify later via DB)
    try:
        for std in ['11th','12th']:
            for b in ['Entrance','Regular']:
                if not Batch.query.filter_by(Standard=std, Stream='Science', name=b).first():
                    db.session.add(Batch(name=b, Standard=std, Stream='Science'))
            for b in ['SP','Maths']:
                if not Batch.query.filter_by(Standard=std, Stream='Commerce', name=b).first():
                    db.session.add(Batch(name=b, Standard=std, Stream='Commerce'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Fetch all batches for client-side filtering and convert to serializable dicts
    raw_batches = Batch.query.order_by(Batch.Standard, Batch.Stream, Batch.name).all()
    all_batches = []
    for b in raw_batches:
        try:
            all_batches.append({
                'id': getattr(b, 'id', None),
                'name': getattr(b, 'name', None),
                'Standard': getattr(b, 'Standard', None),
                'Stream': getattr(b, 'Stream', None),
            })
        except Exception:
            # Skip any non-serializable entries
            continue

    if request.method == "POST":
        Student_name = request.form.get("student_name")
        print(f"message object of student name \n \n :{format(request.form)}")
        Gender = request.form.get("gender")
        DOB = request.form.get("dob")
        School_name = request.form.get("school_name")
        Standard = request.form.get("standard")
        Stream = request.form.get("stream")
        Student_batch = request.form.get("batch")
        # If user provided a batch name via textbox, ensure Batch row exists
        try:
            if Student_batch and Student_batch.strip():
                sb_name = Student_batch.strip()
                # normalize stream value for lookup
                sb_stream = Stream.strip() if Stream else None
                existing_batch = Batch.query.filter_by(name=sb_name, Standard=Standard, Stream=sb_stream).first()
                if not existing_batch:
                    new_batch = Batch(name=sb_name, Standard=Standard, Stream=sb_stream)
                    db.session.add(new_batch)
                    # don't commit now; will commit together with student record
        except Exception:
            db.session.rollback()
        Address = request.form.get("address")
        Father_name = request.form.get("father_name")
        Father_profession = request.form.get("father_profession")
        Mother_name = request.form.get("mother_name")
        Mother_profession = request.form.get("mother_profession")
        Student_number = request.form.get("student_number")
        Parent_number = request.form.get("parent_number")

        # Server-side validation
        errors = []
        # Required checks
        if not Student_name or not Student_name.strip():
            errors.append('Student name is required.')
        if not School_name or not School_name.strip():
            errors.append('School/College name is required.')
        if not Standard or not Standard.strip():
            errors.append('Standard/Batch is required.')
        if not Student_number or not str(Student_number).strip():
            errors.append('Student phone/number is required.')
        if not Parent_number or not str(Parent_number).strip():
            errors.append('Parent phone number is required.')
        if not Gender:
            errors.append('Gender is required.')
        if not DOB:
            errors.append('Date of birth is required.')

        # Validate numeric phone fields
        try:
            if Student_number and not str(Student_number).isdigit():
                errors.append('Student phone/number must contain only digits.')
        except Exception:
            errors.append('Invalid student number.')
        try:
            if Parent_number and not str(Parent_number).isdigit():
                errors.append('Parent phone number must contain only digits.')
        except Exception:
            errors.append('Invalid parent number.')

        # Validate DOB format (expecting YYYY-MM-DD)
        try:
            if DOB:
                datetime.datetime.strptime(DOB, '%Y-%m-%d')
        except Exception:
            errors.append('Date of birth must be in YYYY-MM-DD format.')

        # Uniqueness checks
        try:
            # Student phone/number must be unique across student records.
            # Parent numbers are intentionally NOT checked against existing student numbers
            # (parents may share numbers or reuse a student's number).
            if Student_number and Student_reg.query.filter_by(Student_number=Student_number).first():
                errors.append('Student phone/number is already registered to another student. Student phone must be unique.')
        except Exception:
            # ignore DB errors here; will be caught later
            pass

        # Validate uploaded file extension
        photo_file = request.files.get('photo')
        if photo_file and photo_file.filename:
            if not allowed_file(photo_file.filename):
                errors.append('Uploaded photo must be an image (png/jpg/jpeg/gif).')

        if errors:
            # Re-render form with previous inputs and error list displayed at top
            return render_template('Student_reg.html', parameters=parameters, form=request.form, errors=errors, standards=standards, streams=streams, batches=all_batches)

        # 1. Handle Uploaded File
        photo_file = request.files.get("photo")
        filename = None

        if photo_file and allowed_file(photo_file.filename):
            filename = secure_filename(photo_file.filename)
            photo_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        # 2. Handle Captured Photo (Base64)
        if not filename and request.form.get("captured_image"):
            image_data = request.form["captured_image"]
            image_data = image_data.replace("data:image/png;base64,", "")
            img_bytes = base64.b64decode(image_data)
            filename = f"{Student_name.replace(' ', '_')}.png"
            with open(os.path.join(app.config["UPLOAD_FOLDER"], filename), "wb") as f:
                f.write(img_bytes)
                
        # Ensure Student_photo is never None to satisfy NOT NULL DB constraint
        if not filename:
            filename = 'placeholder.png'
        # Create the Student_reg entry with a temporary unique Student_id so the INSERT succeeds
        DOB = datetime.datetime.strptime(DOB, "%Y-%m-%d")
        doa_store = datetime.date.today()
        numbers = random.sample(range(1, 11), 4)
        numbers = ''.join(str(n) for n in numbers)
        Student_id = Student_name[:4]+doa_store.strftime('%Y')+numbers
        Student_pass= Student_name[:4]+DOB.strftime('%Y')
        entry = Student_reg(
            Student_name=Student_name,
            Gender=Gender,
            DOB=DOB,
            School_name=School_name,
            Standard=Standard,
            Student_batch=Student_batch,
            Stream=Stream,
            Address=Address,
            Father_name=Father_name,
            Father_profession=Father_profession,
            Mother_name=Mother_name,
            Mother_profession=Mother_profession,
            Student_number=Student_number,
            Parent_number=Parent_number,
            Student_photo=filename,
            Student_id=Student_id,
            Student_password=Student_pass,
            DOA=doa_store,
            Added_by=session.get('user'),
            Created_at=datetime.datetime.now()
        )

        db.session.add(entry)
        try:
            # Flush to get Sr_no assigned without committing yet
            db.session.flush()
        except Exception as flush_e:
            # If flush fails, rollback and report
            db.session.rollback()
            print('Failed to insert student entry:', flush_e)
            flash('Failed to register student. Please try again.', 'danger')
            return render_template('Student_reg.html', parameters=parameters, standards=standards, streams=streams, batches=all_batches)

        # Now Sr_no should be available — finalize Student_id and password based on Sr_no
        try:
            sr = entry.Sr_no
            # Build name part (first 4 alphanumeric characters, uppercase)
            cleaned = ''.join([c for c in (Student_name or '') if c.isalnum()])
            name_part = (cleaned[:4].upper()).ljust(4, 'X')
            # Year from DOA (DOA stored in doa_store)
            try:
                year = doa_store.year
            except Exception:
                year = datetime.date.today().year

            generated_id = f"{name_part}{year}{sr:04d}"

            # Generate password: first 4 chars of name + 4-digit random number
            rand_num = f"{secrets.randbelow(10000):04d}"
            generated_password = f"{name_part}{rand_num}"

            # Update the entry with final Student_id and password
            entry.Student_id = generated_id
            entry.Student_password = generated_password
            db.session.add(entry)

            # Commit student record (credentials stored in Student_reg.Student_password)
            try:
                db.session.commit()
                # After successfully committing the student record, create a Login entry
                try:
                    hashed = generate_password_hash(generated_password)
                    now = datetime.datetime.now()
                    lr = Login.query.filter_by(account_id=generated_id).first()
                    if lr:
                        lr.password = hashed
                        lr.role = 'student'
                        lr.last_login = now
                        db.session.add(lr)
                    else:
                        new_lr = Login(account_id=generated_id, password=hashed, role='student', last_login=now)
                        db.session.add(new_lr)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                # Prepare modal data to show registration success with credentials
                modal_name = Student_name
                modal_id = generated_id
                modal_password = generated_password
                flash(f"Student Registered. Student ID: {generated_id}  Password: {generated_password}", 'success')
                return render_template("Student_reg.html", parameters=parameters, generated_id=modal_id, generated_password=modal_password, generated_name=modal_name, standards=standards, streams=streams, batches=all_batches)
            except Exception as le:
                db.session.rollback()
                print('Failed to commit student record:', le)
                flash(f"Student Registered but failed to save record. Student ID: {generated_id}", 'warning')
        except Exception as e:
            db.session.rollback()
            print('Error generating Student_id/password:', e)
            flash('Student registered but failed to generate Student ID/password automatically.', 'warning')
        except Exception as e:
            db.session.rollback()
            print('Error generating Student_id/password:', e)
            flash('Student registered but failed to generate Student ID/password automatically.', 'warning')

        print("Student Registered:", Student_name, "| Photo Saved As:", filename)

    return render_template("Student_reg.html", parameters=parameters, standards=standards, streams=streams, batches=all_batches)


class Attendence(db.Model):
    Attendence_id = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    Class = db.Column(db.String(20), unique=False, nullable=False)
    Subject = db.Column(db.String(100), unique=False, nullable=False)
    Professor_name = db.Column(db.String(100), unique=False, nullable=False)
    Student_id = db.Column(db.String(64), unique=False, nullable=False)
    Student_name = db.Column(db.String(120), unique=False, nullable=False)
    Date = db.Column(db.Date, unique=False, nullable=False)
    Start_time = db.Column(db.String(12), unique=False, nullable=False)
    End_time = db.Column(db.String(12), unique=False, nullable=False)
    Status = db.Column(db.String(10), unique=False, nullable=False)
    Remark = db.Column(db.String(100), unique=False, nullable=False)
    Schedule_id = db.Column(db.Integer, unique=False, nullable=True)
    Marked_at = db.Column(db.DateTime, unique=False, nullable=True)
    Marked_by = db.Column(db.String(80), unique=False, nullable=True)


# Show all classes (batches) in the schedule section
@app.route("/schedule")
@login_required
def schedule_batches():
    # remove_expired_schedules()
    classes = db.session.query(Student_reg.Standard, func.count(Student_reg.Sr_no)).group_by(Student_reg.Standard).all()
    classes = [(c[0], c[1]) for c in classes]
    return render_template("Schedule_batches.html", classes=classes, parameters=parameters)
    
@app.route("/class")
@login_required
def standard():
    # Remove schedules older than today (run cleanup opportunistically)
    # remove_expired_schedules()

    # Query distinct standards and the number of students in each
    classes = db.session.query(Student_reg.Standard, func.count(Student_reg.Sr_no)).group_by(Student_reg.Standard).all()
    # classes is a list of tuples: [(standard, count), ...]
    classes = [(c[0], c[1]) for c in classes]
    print(f"Available Classes with counts: {classes}")
        # Link to /Student/<Standard> to show students in the batch
    return render_template("Standard.html", classes=classes, link_to_schedule=False, parameters=parameters)

@app.route("/Student/<Standard>", methods=['GET', 'POST'])
@login_required
def students_by_standard(Standard):
    Students = Student_reg.query.filter_by(Standard=Standard).all()
    mark_att = Schedule.query.filter_by(Standard=Standard).all()

    if request.method == "POST":
        # Preserve existing attendance-saving behavior on form submit
        for student in Students:
            attendance_status = request.form.get(f'attendance_{student.Student_id}')
            reason = request.form.get(f'reason_{student.Student_id}', '')
            if attendance_status:  # Only save if marked
                # If there's a schedule available, link attendance to it (use first schedule)
                if mark_att:
                    sch = mark_att[0]
                    # Check for existing entry for this schedule+student
                    existing = None
                    if sch.Schedule_id is not None:
                        existing = Attendence.query.filter_by(Schedule_id=sch.Schedule_id, Student_id=student.Student_id).first()
                    if not existing:
                        # fallback to matching on schedule fields
                        existing = Attendence.query.filter_by(
                            Class=Standard,
                            Subject=sch.Subject,
                            Professor_name=sch.Professor_name,
                            Date=sch.Date,
                            Start_time=sch.Start_time,
                            End_time=sch.End_time,
                            Student_id=student.Student_id
                        ).first()

                    if existing:
                        existing.Status = attendance_status
                        existing.Remark = reason
                        existing.Marked_at = datetime.datetime.now()
                        existing.Marked_by = session.get('user') if 'user' in session else None
                        db.session.add(existing)
                    else:
                        entry = Attendence(
                            Class=Standard,
                            Professor_name=sch.Professor_name,
                            Subject=sch.Subject,
                            Student_id=student.Student_id,
                            Student_name=student.Student_name,
                            Date=sch.Date,
                            Start_time=sch.Start_time,
                            End_time=sch.End_time,
                            Status=attendance_status,
                            Remark=reason,
                            Schedule_id=sch.Schedule_id,
                            Marked_at=datetime.datetime.now(),
                            Marked_by=session.get('user') if 'user' in session else None
                        )
                        db.session.add(entry)
                else:
                    # No schedule available — check for existing by class/date/student
                    existing = Attendence.query.filter_by(
                        Class=Standard,
                        Student_id=student.Student_id,
                        Date=datetime.datetime.now().strftime("%Y-%m-%d")
                    ).first()
                    if existing:
                        existing.Status = attendance_status
                        existing.Remark = reason
                        existing.Marked_at = datetime.datetime.now()
                        existing.Marked_by = session.get('user') if 'user' in session else None
                        db.session.add(existing)
                    else:
                        entry = Attendence(
                            Class=Standard,
                            Professor_name='N/A',
                            Subject='N/A',
                            Student_id=student.Student_id,
                            Student_name=student.Student_name,
                            Date=datetime.datetime.now().strftime("%Y-%m-%d"),
                            Start_time='N/A',
                            End_time='N/A',
                            Status=attendance_status,
                            Remark=reason,
                            Marked_at=datetime.datetime.now(),
                            Marked_by=session.get('user') if 'user' in session else None
                        )
                        db.session.add(entry)
        db.session.commit()
        flash('Attendance marked successfully!', 'success')
        return redirect(url_for('standard'))

    # For a GET request, show the students-only list (reuse `home.html` layout)
    # This displays student cards similar to the homepage instead of the attendance form.
    return render_template("home.html", students=Students, current_standard=Standard, parameters=parameters)


@app.route("/student_detail/<int:student_id>")
@app.route("/student_detail/<student_id>")
@login_required
def student_detail(student_id):
    # Lookup by Student_id (string) instead of numeric Sr_no
    student = Student_reg.query.filter_by(Student_id=student_id).first()
    if not student:
        flash('Student not found!', 'danger')
        return redirect(url_for('home'))
    
    # Support query params for filtering and pagination
    start = request.args.get('start')
    end = request.args.get('end')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    query = Attendence.query.filter(Attendence.Student_id == student.Student_id)
    # Apply start/end filters if provided, else default to DOA..today
    if start:
        try:
            query = query.filter(Attendence.Date >= start)
        except Exception:
            pass
    else:
        if getattr(student, 'DOA', None):
            try:
                query = query.filter(Attendence.Date >= student.DOA)
            except Exception:
                pass

    if end:
        try:
            query = query.filter(Attendence.Date <= end)
        except Exception:
            pass

    total = query.count()
    attendance_records = query.order_by(Attendence.Date.asc()).limit(per_page).offset((page-1)*per_page).all()

    attendance_start = start or (student.DOA.isoformat() if getattr(student, 'DOA', None) else None)
    attendance_end = end or datetime.datetime.now().strftime('%Y-%m-%d')

    pagination = {
        'page': page,
        'per_page': per_page,
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page else 1
    }
    
    # Get student password (plaintext from Student_reg) for admin/root to view
    student_password = None
    if session.get('role') in ['admin', 'root']:
        student_password = student.Student_password  # Use plaintext password from Student_reg

    return render_template("student_detail.html", student=student, student_password=student_password, attendance_records=attendance_records, parameters=parameters, attendance_start=attendance_start, attendance_end=attendance_end, pagination=pagination)

    
@app.route('/student_detail/<student_id>/export')
@login_required
def export_student_attendance(student_id):
    # Export by Student_id (string)
    student = Student_reg.query.filter_by(Student_id=student_id).first()
    if not student:
        flash('Student not found!', 'danger')
        return redirect(url_for('home'))

    start = request.args.get('start')
    end = request.args.get('end')

    query = Attendence.query.filter(Attendence.Student_id == student.Student_id)
    if start:
        try:
            query = query.filter(Attendence.Date >= start)
        except Exception:
            pass
    else:
        if getattr(student, 'DOA', None):
            try:
                query = query.filter(Attendence.Date >= student.DOA)
            except Exception:
                pass
    if end:
        try:
            query = query.filter(Attendence.Date <= end)
        except Exception:
            pass

    records = query.order_by(Attendence.Date.asc()).all()

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Class', 'Subject', 'Professor', 'Start_time', 'End_time', 'Status', 'Remark'])
    for r in records:
        writer.writerow([getattr(r, 'Date'), r.Class, r.Subject, r.Professor_name, r.Start_time, r.End_time, r.Status, r.Remark])
    output.seek(0)

    response = make_response(output.getvalue())
    filename = f"attendance_{student.Student_id}_{datetime.datetime.now().strftime('%Y%m%d')}.csv"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv'
    return response

    return render_template("student_detail.html", student=student, attendance_records=attendance_records, parameters=parameters, attendance_start=attendance_start, attendance_end=attendance_end, pagination=pagination)


class Schedule(db.Model):
    Schedule_id = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    Date = db.Column(db.String(20), unique=False, nullable=False)
    Standard = db.Column(db.String(20), unique=False, nullable=False)
    Subject = db.Column(db.String(20), unique=False, nullable=False)
    Start_time = db.Column(db.String(20), unique=False, nullable=False)
    End_time = db.Column(db.String(20), unique=False, nullable=False)
    Professor_name = db.Column(db.String(100), unique=False, nullable=False)
    # Who created the schedule (admin id)
    Added_by = db.Column(db.String(80), unique=False, nullable=True)
    # Comma-separated list of admin ids who are allowed to see/edit this schedule
    Allowed_admins = db.Column(db.String(500), unique=False, nullable=True)
    # The admin id who is designated to mark attendance for this schedule
    Marker = db.Column(db.String(80), unique=False, nullable=True)


class ScheduleAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    schedule_id = db.Column(db.Integer, unique=False, nullable=True)
    action = db.Column(db.String(20), unique=False, nullable=False)  # create | edit | delete
    user = db.Column(db.String(80), unique=False, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)
    details = db.Column(db.Text, unique=False, nullable=True)


class Exam(db.Model):
    """Exam schedule — defines exam date, subject, and class/batch."""
    Exam_id = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    Date = db.Column(db.Date, unique=False, nullable=False)
    Standard = db.Column(db.String(20), unique=False, nullable=False)
    Subject = db.Column(db.String(100), unique=False, nullable=False)
    Start_time = db.Column(db.String(12), unique=False, nullable=False)
    End_time = db.Column(db.String(12), unique=False, nullable=False)
    Total_marks = db.Column(db.Integer, unique=False, nullable=True)
    Professor_name = db.Column(db.String(100), unique=False, nullable=False)
    Created_at = db.Column(db.DateTime, default=datetime.datetime.now)


class ExamMarks(db.Model):
    """Student exam marks — one record per student per exam."""
    Mark_id = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    Exam_id = db.Column(db.Integer, unique=False, nullable=False)
    Student_id = db.Column(db.String(64), unique=False, nullable=False)
    Student_name = db.Column(db.String(120), unique=False, nullable=False)
    Marks_obtained = db.Column(db.Float, unique=False, nullable=True)
    Remarks = db.Column(db.String(200), unique=False, nullable=True)
    Entered_by = db.Column(db.String(80), unique=False, nullable=True)
    Entered_at = db.Column(db.DateTime, default=datetime.datetime.now)


class ExamRank(db.Model):
    """Cached per-exam rankings to ensure ranks update immediately after marks change."""
    id = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    Exam_id = db.Column(db.Integer, unique=False, nullable=False)
    Student_id = db.Column(db.String(64), unique=False, nullable=False)
    Rank = db.Column(db.Integer, unique=False, nullable=True)
    Marks = db.Column(db.Float, unique=False, nullable=True)
    Percentage = db.Column(db.Float, unique=False, nullable=True)


class Promotionaudit(db.Model):
    """Records each promotion action for auditing."""
    id = db.Column(db.Integer, primary_key=True, nullable=False, unique=True)
    Student_id = db.Column(db.String(64), unique=False, nullable=False)
    Student_name = db.Column(db.String(120), unique=False, nullable=True)
    From_standard = db.Column(db.String(20), unique=False, nullable=True)
    To_standard = db.Column(db.String(20), unique=False, nullable=True)
    Promoted_by = db.Column(db.String(80), unique=False, nullable=True)
    Timestamp = db.Column(db.DateTime, default=datetime.datetime.now)
    Notes = db.Column(db.String(200), unique=False, nullable=True)

class ExamAttendance(db.Model):
    """Attendance for each exam."""
    Attend_id = db.Column(db.Integer, primary_key=True)
    Exam_id = db.Column(db.Integer, nullable=False)
    Student_id = db.Column(db.String(64), nullable=False)
    Student_name = db.Column(db.String(120), nullable=False)
    Status = db.Column(db.String(10), nullable=False)  # Present / Absent
    Marked_at = db.Column(db.DateTime, default=datetime.datetime.now)



@app.route("/Add_schedule", methods=['GET', 'POST'])
@login_required
def add_schedule():
    # Get distinct standards from Student_reg
    Standards = db.session.query(Student_reg.Standard).distinct().all()
    classes = [s[0] for s in Standards]  # Extract the standard string from tuple

    # Cleanup expired schedules before showing the add form
    # remove_expired_schedules()

    # Fetch admin list to allow selecting marker/allowed admins
    admins_list = Admin.query.order_by(Admin.Name.asc()).all()

    if request.method == "POST":
        class_id = request.form.get("class_id")
        subject = request.form.get("subject")
        date = request.form.get("date")
        start_hour = request.form.get("start_hour")
        start_minute = request.form.get("start_minute")
        start_period = request.form.get("start_period", "AM")
        end_hour = request.form.get("end_hour")
        end_minute = request.form.get("end_minute")
        end_period = request.form.get("end_period", "AM")
        professor_name = request.form.get("professor_name")
        marker = request.form.get('marker')
        allowed_admins = request.form.getlist('allowed_admins') or []
        allowed_admins_str = ','.join([a for a in allowed_admins if a]) if allowed_admins else None

        # Format time display as HH:MM AM/PM
        display_start_time = f"{start_hour}:{start_minute} {start_period}" if start_hour and start_minute else ""
        display_end_time = f"{end_hour}:{end_minute} {end_period}" if end_hour and end_minute else ""

        # Validation: marker and allowed_admins are required
        if not marker or not allowed_admins_str:
            flash('Please select a Designated Marker and at least one Visible To admin.', 'danger')
            return render_template('Add_schedule.html', classes=classes, admins=admins_list, form=request.form)

        new_schedule = Schedule(
            Date=date,
            Standard=class_id,
            Subject=subject,
            Start_time=display_start_time,
            End_time=display_end_time,
            Professor_name=professor_name,
            Added_by=session.get('user'),
            Marker=marker,
            Allowed_admins=allowed_admins_str
        )
            # Overlap validation: ensure no other schedule for same Standard & Date overlaps in time
        try:
                # convert times to comparable integers HHMM
            def to_int_time(t):
                return int(t.replace(':','').replace(' AM','').replace(' PM','')) if t and ':' in t else 0
            ns = to_int_time(display_start_time)
            ne = to_int_time(display_end_time)
            collisions = Schedule.query.filter_by(Standard=class_id, Date=date).all()
            for c in collisions:
                cs = to_int_time(c.Start_time)
                ce = to_int_time(c.End_time)
                # overlap if start < existing_end and end > existing_start
                if ns < ce and ne > cs:
                    flash(f'Cannot add schedule: overlaps with existing schedule {c.Subject} ({c.Start_time}-{c.End_time})', 'danger')
                    return render_template('Add_schedule.html', classes=classes, form=request.form)

            db.session.add(new_schedule)
            db.session.commit()
            # Audit create
            try:
                details = {'Date': date, 'Standard': class_id, 'Subject': subject, 'Start_time': display_start_time, 'End_time': display_end_time, 'Professor_name': professor_name}
                audit = ScheduleAudit(schedule_id=new_schedule.Schedule_id, action='create', user=session.get('user'), details=json.dumps(details))
                db.session.add(audit)
                db.session.commit()
            except Exception:
                db.session.rollback()

            flash('Schedule added successfully!', 'success')
            return render_template('Add_schedule.html', classes=classes, admins=admins_list, show_success=True)
        except Exception as e:
            db.session.rollback()
            print('Failed to add schedule:', e)
            flash('Failed to add schedule.', 'danger')

    return render_template("Add_schedule.html", classes=classes, admins=admins_list)


@app.route('/create_admin', methods=['GET', 'POST'])
@login_required
def create_admin():
    # Only root (from config) can create admin accounts
    admins = Admin.query.order_by(Admin.Created_at.desc()).all()
    length = len(admins)
    if session.get('role') != 'root':
        flash('Access denied. Root login required.', 'danger')
        return redirect(url_for('login'))

    generated_id = None
    generated_password = None

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')

        # Handle photo upload
        photo_file = request.files.get("photo")
        filename = None

        if photo_file and allowed_file(photo_file.filename):
            filename = secure_filename(photo_file.filename)
            photo_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        
        # Use placeholder if no photo was uploaded
        if not filename:
            filename = 'placeholder.png'

        # Generate Admin_id and password
        cleaned = ''.join([c for c in name if c.isalnum()])
        name_part = (cleaned[:5].upper())  # First 5 letters
        now = datetime.datetime.now()
        time_part = now.strftime("%H%M")  # Hour and minutes (HHMM)
        generated_password = f"{name_part}{time_part}"
        rand_num = f"{secrets.randbelow(10000):04d}"
        generated_id = f"{name_part}@admin{length}{rand_num}"

         # Server-side validation

        try:
            # Store admin credentials in Admin table (single source of truth)
            admin = Admin(Admin_id=generated_id, Password=generated_password, Name=name, Email=email, Phone=phone, Photo=filename)
            db.session.add(admin)
            db.session.commit()

            # Create or update Login entry for this admin (store hashed password)
            try:
                hashed = generate_password_hash(generated_password)
                lr = Login.query.filter_by(account_id=generated_id).first()
                now = datetime.datetime.now()
                if lr:
                    lr.password = hashed
                    lr.role = 'admin'
                    lr.last_login = now
                    db.session.add(lr)
                else:
                    new_lr = Login(account_id=generated_id, password=hashed, role='admin', last_login=now)
                    db.session.add(new_lr)
                db.session.commit()
            except Exception:
                db.session.rollback()

            # Pass the credentials to template without using flash
            return render_template('admin_create.html', parameters=parameters, generated_id=generated_id, generated_password=generated_password, success=True)
        except Exception as e:
            db.session.rollback()
            print('Failed to create admin:', e)
            flash(f'Failed to create admin user: {str(e)}', 'danger')

    return render_template('admin_create.html', parameters=parameters)


@app.route('/admin_profile/<admin_id>')
@login_required
def admin_profile(admin_id):
    admin = Admin.query.filter_by(Admin_id=admin_id).first()
    if not admin:
        flash('Admin not found', 'danger')
        return redirect(url_for('home'))
    # Try to get last login info from Login table (best-effort; may be creation time if last_login not tracked)
    admin_last_login = None
    try:
        login_row = Login.query.filter_by(account_id=admin.Admin_id).first()
        if login_row:
            admin_last_login = getattr(login_row, 'last_login', None) or getattr(login_row, 'created_at', None)
    except Exception:
        admin_last_login = None

    return render_template('admin_profile.html', admin=admin, parameters=parameters, admin_last_login=admin_last_login)


@app.route('/root_dashboard')
@login_required
def root_dashboard():
    if session.get('role') != 'root':
        flash('Access denied. Root login required.', 'danger')
        return redirect(url_for('login'))
    admins = Admin.query.order_by(Admin.Created_at.desc()).all()
    
    # Fetch passwords for each admin from Admin table (single source)
    admin_passwords = {admin.Admin_id: getattr(admin, 'Password', '') for admin in admins}
    
    total_admins = len(admins)
    total_students = Student_reg.query.count()
    return render_template('root_dashboard.html', admins=admins, admin_passwords=admin_passwords, total_admins=total_admins, total_students=total_students, parameters=parameters)


@app.route('/promote', methods=['GET','POST'])
@login_required
def promote():
    # Only admin/root may promote
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))

    # Define ordered standards and promotable set
    order = ['1st','2nd','3rd','4th','5th','6th','7th','8th','9th','10th','11th','12th']
    promotable = set(['1st','2nd','3rd','4th','5th','6th','7th','8th','9th','11th'])
    next_map = {s: (order[i+1] if i+1 < len(order) else None) for i,s in enumerate(order)}

    # Allow optional filter by standard via query param
    std_filter = request.args.get('standard')

    # Build query: only students currently in promotable standards
    query = Student_reg.query.filter(Student_reg.Standard.in_(list(promotable)))
    if std_filter and std_filter != 'ALL':
        query = query.filter_by(Standard=std_filter)

    students = query.order_by(Student_reg.Standard.asc(), Student_reg.Student_name.asc()).all()

    # If a specific student_id was provided via query param, limit view to that student
    q_student = request.args.get('student_id')
    if q_student:
        s = Student_reg.query.filter_by(Student_id=q_student).first()
        if s and s.Standard in promotable:
            students = [s]

    if request.method == 'POST':
        # Two-step flow: initial POST shows confirmation; confirm POST executes promotion.
        action = request.form.get('action')
        promote_ids = request.form.getlist('promote_ids')
        if not promote_ids:
            flash('No students selected for promotion.', 'warning')
            return render_template('promote.html', students=students, next_map=next_map)

        # Build list of Student_reg objects to operate on
        sel_students = []
        for sid in promote_ids:
            st = Student_reg.query.filter_by(Student_id=sid).first()
            if st:
                sel_students.append(st)
        print(f"Selected students: {len(sel_students)} for ids: {promote_ids}")

        # If user requested CSV export, generate CSV of selected students
        if action == 'export':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Student_id', 'Student_name', 'From_standard', 'To_standard'])
            for s in sel_students:
                writer.writerow([s.Student_id, s.Student_name, s.Standard, next_map.get(s.Standard, '')])
            output.seek(0)
            response = make_response(output.getvalue())
            filename = f"promote_preview_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            response.headers['Content-Disposition'] = f'attachment; filename={filename}'
            response.headers['Content-Type'] = 'text/csv'
            return response

        # If this is the initial submission (no confirm) show confirmation page
        if request.form.get('confirm') is None and action != 'confirm':
            return render_template('promote_confirm.html', students=sel_students, next_map=next_map)

        # If action is confirm (or confirm flag present), perform promotion and audit
        if action == 'confirm' or request.form.get('confirm'):
            promoted = []
            skipped = []
            audits = []
            promoted_details = []
            for st in sel_students:
                cur = st.Standard
                nxt = next_map.get(cur)
                print(f"Student {st.Student_id} in {cur}, next: {nxt}")
                if not nxt:
                    skipped.append(st.Student_id)
                    continue
                old = cur
                st.Standard = nxt
                db.session.add(st)
                promoted.append(st.Student_id)
                promoted_details.append(f'{st.Student_id} ({st.Student_name}) from {old} to {nxt}')
                try:
                    audit = Promotionaudit(Student_id=st.Student_id, Student_name=st.Student_name, From_standard=old, To_standard=nxt, Promoted_by=session.get('user'), Notes='Bulk promotion')
                    db.session.add(audit)
                    audits.append(audit)
                    print(f"Prmotion Audit record result to db for {st.Student_id} : {audit}")
                except Exception:
                    pass

            try:
                db.session.commit()
                flash(f'Promoted {len(promoted)} students.', 'success')
                if skipped:
                    flash(f'Skipped {len(skipped)} students (no next standard available).', 'warning')
                for detail in promoted_details:
                    flash(f'Promoted: {detail}', 'info')
            except Exception as e:
                db.session.rollback()
                print('Failed to promote students:', e)
                flash('Failed to promote students. See server logs.', 'danger')

            return redirect(url_for('home'))

    return render_template('promote.html', students=students, next_map=next_map)


@app.route('/promote_batch', methods=['POST'])
@login_required
def promote_batch():
    # Only admin/root may promote
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))

    batch_id = request.form.get('batch_id')
    if not batch_id:
        flash('No batch specified.', 'warning')
        return redirect(url_for('batches_admin'))

    batch = Batch.query.filter_by(id=batch_id).first()
    if not batch:
        flash('Batch not found.', 'warning')
        return redirect(url_for('batches_admin'))

    # Define promotable standards and next mapping (reuse logic from promote())
    order = ['1st','2nd','3rd','4th','5th','6th','7th','8th','9th','10th','11th','12th']
    promotable = set(['1st','2nd','3rd','4th','5th','6th','7th','8th','9th','11th'])
    next_map = {s: (order[i+1] if i+1 < len(order) else None) for i,s in enumerate(order)}

    # Select students in this batch and standard
    students_in_batch = Student_reg.query.filter_by(Student_batch=batch.name, Standard=batch.Standard).all()

    # Filter to promotable students only
    sel_students = [s for s in students_in_batch if s.Standard in promotable and s.Standard not in ['10th','12th']]

    if not sel_students:
        flash('No promotable students found in selected batch.', 'info')
        return redirect(url_for('batches_admin'))

    # If confirmation flag present, perform promotion
    if request.form.get('confirm'):
        promoted = []
        for st in sel_students:
            cur = st.Standard
            nxt = next_map.get(cur)
            if not nxt:
                continue
            old = cur
            st.Standard = nxt
            db.session.add(st)
            try:
                audit = Promotionaudit(Student_id=st.Student_id, Student_name=st.Student_name, From_standard=old, To_standard=nxt, Promoted_by=session.get('user'), Notes=f'Batch promotion for batch {batch.name}')
                db.session.add(audit)
            except Exception:
                pass

        try:
            db.session.commit()
            flash(f'Promoted {len(sel_students)} students from batch {batch.name}.', 'success')
        except Exception as e:
            db.session.rollback()
            print('Failed to promote batch:', e)
            flash('Failed to promote batch. See server logs.', 'danger')

        return redirect(url_for('admin_batches'))

    # Otherwise show confirmation page (reuse promote_confirm template)
    return render_template('promote_confirm.html', students=sel_students, next_map=next_map, batch_id=batch_id, is_batch_promotion=True)


@app.route('/promote_class', methods=['POST'])
@login_required
def promote_class():
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied.', 'danger')
        return redirect(url_for('admin_batches'))
    
    standard = request.form.get('standard')
    if not standard:
        flash('No standard selected.', 'danger')
        return redirect(url_for('admin_batches'))
    
    order = ['1st','2nd','3rd','4th','5th','6th','7th','8th','9th','10th','11th','12th']
    next_map = {s: (order[i+1] if i+1 < len(order) else None) for i,s in enumerate(order)}
    
    if standard not in next_map or next_map[standard] is None:
        flash('Cannot promote this class.', 'warning')
        return redirect(url_for('admin_batches'))
    
    students = Student_reg.query.filter_by(Standard=standard).all()
    if not students:
        flash('No students in this class.', 'info')
        return redirect(url_for('admin_batches'))
    
    # Promote all
    for s in students:
        s.Standard = next_map[standard]
    
    db.session.commit()
    flash(f'Promoted {len(students)} students from {standard} to {next_map[standard]}.', 'success')
    return redirect(url_for('admin_batches'))


@app.route('/root_profile')
@login_required
def root_profile():
    if session.get('role') != 'root':
        flash('Access denied. Root login required.', 'danger')
        return redirect(url_for('login'))

    admin_user = parameters.get('Admin_user')
    # System stats
    total_admins = Admin.query.count()
    total_students = Student_reg.query.count()

    # Try to find a login row for root (may not exist)
    login_row = None
    try:
        login_row = Login.query.filter_by(account_id=admin_user).first()
    except Exception:
        login_row = None

    # Determine last login: prefer a 'last_login' attribute if present, else use created_at or N/A
    last_login = None
    if login_row:
        last_login = getattr(login_row, 'last_login', None) or getattr(login_row, 'created_at', None)

    return render_template('root_profile.html', parameters=parameters, total_admins=total_admins, total_students=total_students, last_login=last_login)


@app.route('/api/system_stats')
@login_required
def api_system_stats():
    # Return simple system counts for dashboard/profile widgets
    try:
        admins = Admin.query.count()
        students = Student_reg.query.count()
        return jsonify({'total_admins': admins, 'total_students': students})
    except Exception as e:
        print('Failed to fetch system stats:', e)
        return jsonify({'total_admins': 0, 'total_students': 0})


@app.route('/student_dashboard')
@login_required
def student_dashboard():
    if session.get('role') != 'student':
        flash('Access denied. Student login required.', 'danger')
        return redirect(url_for('login'))
    
    student_id = session.get('user')
    student = Student_reg.query.filter_by(Student_id=student_id).first()
    
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('login'))
    
    # Attendance statistics
    try:
        all_attendance = Attendence.query.filter(Attendence.Student_id == student_id).all()
        total_classes = len(all_attendance)
        present_count = len([a for a in all_attendance if a.Status and a.Status.lower() in ('present', 'p', 'yes')])
        absent_count = len([a for a in all_attendance if a.Status and a.Status.lower() in ('absent', 'a', 'no')])
        attendance_percentage = round((present_count / total_classes * 100), 1) if total_classes > 0 else 0
    except Exception as e:
        print('Error fetching attendance stats:', e)
        total_classes = 0
        present_count = 0
        absent_count = 0
        attendance_percentage = 0
    
    # Recent attendance (last 10 records)
    try:
        recent_attendance = Attendence.query.filter(Attendence.Student_id == student_id).order_by(Attendence.Date.desc()).limit(10).all()
    except Exception as e:
        print('Error fetching recent attendance:', e)
        recent_attendance = []
    
    # Today's schedules for student's class (ignore time portion)
    try:
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        today_schedules = Schedule.query.filter(Schedule.Standard == student.Standard, Schedule.Date.like(f"{today}%"))
        today_schedules = today_schedules.order_by(Schedule.Start_time.asc()).all()
    except Exception as e:
        print('Error fetching schedules:', e)
        today_schedules = []
    
    # Exam performance data (recent exams with marks)
    try:
        exam_marks = ExamMarks.query.filter_by(Student_id=student_id).order_by(ExamMarks.Entered_at.desc()).limit(5).all()
        # Fetch associated exam details
        exam_performance = []
        for mark in exam_marks:
            exam = Exam.query.filter_by(Exam_id=mark.Exam_id).first()
            if exam:
                exam_performance.append({
                    'exam': exam,
                    'marks': mark
                })
    except Exception as e:
        print('Error fetching exam performance:', e)
        exam_performance = []
    
    # Get login info for student
    try:
        login_row = Login.query.filter_by(account_id=student_id).first()
        last_login = getattr(login_row, 'last_login', None) if login_row else None
    except Exception as e:
        print('Error fetching last login:', e)
        last_login = None
    
    return render_template('student_dashboard.html', 
                         student=student,
                         total_classes=total_classes,
                         present_count=present_count,
                         absent_count=absent_count,
                         attendance_percentage=attendance_percentage,
                         recent_attendance=recent_attendance,
                         today_schedules=today_schedules,
                         exam_performance=exam_performance,
                         last_login=last_login,
                         parameters=parameters)


@app.route('/delete_admin/<admin_id>', methods=['POST'])
@login_required
def delete_admin(admin_id):
    if session.get('role') != 'root':
        flash('Access denied. Root login required.', 'danger')
        return redirect(url_for('login'))
    admin = Admin.query.filter_by(Admin_id=admin_id).first()
    if not admin:
        flash('Admin not found.', 'danger')
        return redirect(url_for('root_dashboard'))
    try:
        # remove photo file if present
        if getattr(admin, 'Photo', None):
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], admin.Photo))
            except Exception:
                pass
        # remove login entries
        Login.query.filter_by(account_id=admin_id).delete()
        db.session.delete(admin)
        db.session.commit()
        flash('Admin deleted successfully.', 'success')
    except Exception as e:
        print('Failed to delete admin:', e)
        flash('Failed to delete admin.', 'danger')
    return redirect(url_for('root_dashboard'))


@app.route('/reset_admin_password/<admin_id>', methods=['POST'])
@login_required
def reset_admin_password(admin_id):
    if session.get('role') != 'root':
        flash('Access denied. Root login required.', 'danger')
        return redirect(url_for('login'))
    admin = Admin.query.filter_by(Admin_id=admin_id).first()
    if not admin:
        flash('Admin not found.', 'danger')
        return redirect(url_for('root_dashboard'))
    try:
        # generate new password: first5 letters + HHMM
        cleaned = ''.join([c for c in admin.Name if c.isalnum()])
        name_part = (cleaned[:5].upper())
        now = datetime.datetime.now()
        time_part = now.strftime("%H%M")
        new_password = f"{name_part}{time_part}"
        # Store password in Admin table (single source)
        admin.Password = new_password
        db.session.add(admin)
        # Remove any legacy Login credential entries and create/update a tracking row
        try:
            Login.query.filter_by(account_id=admin.Admin_id).delete()
            tracking = Login(account_id=admin.Admin_id, password='', role='admin', last_login=datetime.datetime.now())
            db.session.add(tracking)
        except Exception:
            pass
        db.session.commit()
        flash(f'Password reset. New password for {admin.Admin_id}: {new_password}', 'success')
    except Exception as e:
        print('Failed to reset admin password:', e)
        flash('Failed to reset password.', 'danger')
    return redirect(url_for('root_dashboard'))


@app.route('/edit_admin/<admin_id>', methods=['GET','POST'])
@login_required
def edit_admin(admin_id):
    if session.get('role') != 'root':
        flash('Access denied. Root login required.', 'danger')
        return redirect(url_for('login'))
    admin = Admin.query.filter_by(Admin_id=admin_id).first()
    if not admin:
        flash('Admin not found', 'danger')
        return redirect(url_for('root_dashboard'))
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        reset = request.form.get('reset_password')
        
        # Handle photo upload
        photo_file = request.files.get("photo")
        if photo_file and allowed_file(photo_file.filename):
            filename = secure_filename(photo_file.filename)
            photo_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            admin.Photo = filename
        
        admin.Name = name
        admin.Email = email
        admin.Phone = phone
        db.session.add(admin)
        
        if reset:
            # generate new password with first 5 letters + HHMM
            cleaned = ''.join([c for c in name if c.isalnum()])
            name_part = (cleaned[:5].upper())
            now = datetime.datetime.now()
            time_part = now.strftime("%H%M")
            new_password = f"{name_part}{time_part}"
            # update Admin table password (single source)
            admin.Password = new_password
            db.session.add(admin)
            # Remove legacy Login credentials and add tracking row
            try:
                Login.query.filter_by(account_id=admin.Admin_id).delete()
                tracking = Login(account_id=admin.Admin_id, password='', role='admin', last_login=datetime.datetime.now())
                db.session.add(tracking)
            except Exception:
                pass
            flash(f'Admin updated. New password: {new_password}', 'success')
        db.session.commit()
        return redirect(url_for('root_dashboard'))
    return render_template('admin_edit.html', admin=admin, parameters=parameters)


@app.route('/edit_schedule/<int:schedule_id>', methods=['GET','POST'])
@login_required
def edit_schedule(schedule_id):
    # Allow edit by root, the adder, or any admin listed in Allowed_admins
    user = session.get('user')
    role = session.get('role')

    schedule = Schedule.query.filter_by(Schedule_id=schedule_id).first()
    if not schedule:
        flash('Schedule not found.', 'danger')
        return redirect(url_for('schedule_batches'))
    # visibility check
    def _allowed_for_change(sch, user, role):
        if role == 'root':
            return True
        if not user:
            return False
        if getattr(sch, 'Added_by', None) == user:
            return True
        if getattr(sch, 'Marker', None) == user:
            return True
        allowed = (getattr(sch, 'Allowed_admins') or '')
        allowed_list = [a.strip() for a in allowed.split(',') if a.strip()]
        if user in allowed_list:
            return True
        return False

    if not _allowed_for_change(schedule, user, role):
        flash('Access denied. Only root, the adder, or specified admins may edit this schedule.', 'danger')
        return redirect(url_for('schedule_batches'))

    # Fetch admin list for template (to allow changing Marker/Allowed_admins)
    admins_list = Admin.query.order_by(Admin.Name.asc()).all()

    if request.method == 'POST':
        # Update fields from form
        subject = request.form.get('subject')
        date = request.form.get('date')
        start_hour = request.form.get('start_hour')
        start_minute = request.form.get('start_minute')
        start_period = request.form.get('start_period', 'AM')
        end_hour = request.form.get('end_hour')
        end_minute = request.form.get('end_minute')
        end_period = request.form.get('end_period', 'AM')
        professor_name = request.form.get('professor_name')
        marker = request.form.get('marker')
        allowed_admins = request.form.getlist('allowed_admins') or []
        allowed_admins_str = ','.join([a for a in allowed_admins if a]) if allowed_admins else None

        # Format time display as HH:MM AM/PM
        display_start_time = f"{start_hour}:{start_minute} {start_period}" if start_hour and start_minute else ""
        display_end_time = f"{end_hour}:{end_minute} {end_period}" if end_hour and end_minute else ""

        # Validate overlaps for the updated time (ignore the current schedule id)
        try:
            def to_int_time(t):
                return int(t.replace(':','').replace(' AM','').replace(' PM','')) if t and ':' in t else 0

            ns = to_int_time(display_start_time)
            ne = to_int_time(display_end_time)
            collisions = Schedule.query.filter(Schedule.Standard==schedule.Standard, Schedule.Date==date, Schedule.Schedule_id!=schedule.Schedule_id).all()
            for c in collisions:
                cs = to_int_time(c.Start_time)
                ce = to_int_time(c.End_time)
                if ns < ce and ne > cs:
                    flash(f'Cannot update schedule: overlaps with existing schedule {c.Subject} ({c.Start_time}-{c.End_time})', 'danger')
                    return render_template('edit_schedule.html', schedule=schedule, parameters=parameters)

            # Save old snapshot for audit
            old = {'Date': schedule.Date, 'Start_time': schedule.Start_time, 'End_time': schedule.End_time, 'Subject': schedule.Subject, 'Professor_name': schedule.Professor_name}

            if subject:
                schedule.Subject = subject
            if date:
                schedule.Date = date
            if start_hour and start_minute:
                schedule.Start_time = display_start_time
            if end_hour and end_minute:
                schedule.End_time = display_end_time
            if professor_name:
                schedule.Professor_name = professor_name
            # update marker/allowed_admins if provided
            schedule.Marker = marker
            schedule.Allowed_admins = allowed_admins_str

            db.session.add(schedule)
            db.session.commit()

            # Audit edit
            try:
                new = {'Date': schedule.Date, 'Start_time': schedule.Start_time, 'End_time': schedule.End_time, 'Subject': schedule.Subject, 'Professor_name': schedule.Professor_name}
                details = {'before': old, 'after': new}
                audit = ScheduleAudit(schedule_id=schedule.Schedule_id, action='edit', user=session.get('user'), details=json.dumps(details))
                db.session.add(audit)
                db.session.commit()
            except Exception:
                db.session.rollback()

            flash('Schedule updated successfully. Existing attendance records are preserved.', 'success')
            return redirect(url_for('show_schedule', Standard=schedule.Standard, date=schedule.Date))
        except Exception as e:
            db.session.rollback()
            print('Failed to update schedule:', e)
            flash('Failed to update schedule.', 'danger')

    return render_template('edit_schedule.html', schedule=schedule, parameters=parameters, admins=admins_list)


@app.route('/delete_schedule/<int:schedule_id>', methods=['POST'])
@login_required
def delete_schedule(schedule_id):
    # Allow deletion by root, the adder, or any admin listed in Allowed_admins
    user = session.get('user')
    role = session.get('role')

    schedule = Schedule.query.filter_by(Schedule_id=schedule_id).first()
    if not schedule:
        flash('Schedule not found.', 'danger')
        return redirect(url_for('schedule_batches'))

    def _allowed_for_delete(sch, user, role):
        if role == 'root':
            return True
        if not user:
            return False
        if getattr(sch, 'Added_by', None) == user:
            return True
        allowed = (getattr(sch, 'Allowed_admins') or '')
        allowed_list = [a.strip() for a in allowed.split(',') if a.strip()]
        if user in allowed_list:
            return True
        return False

    if not _allowed_for_delete(schedule, user, role):
        flash('Access denied. Only root, the adder, or specified admins may delete this schedule.', 'danger')
        return redirect(url_for('schedule_batches'))

    try:
        # Do NOT delete attendance; only remove the schedule record
        # Save snapshot for audit
        try:
            snap = {'Date': schedule.Date, 'Start_time': schedule.Start_time, 'End_time': schedule.End_time, 'Subject': schedule.Subject, 'Professor_name': schedule.Professor_name}
            audit = ScheduleAudit(schedule_id=schedule.Schedule_id, action='delete', user=session.get('user'), details=json.dumps(snap))
            db.session.add(audit)
        except Exception:
            db.session.rollback()

        db.session.delete(schedule)
        db.session.commit()
        flash('Schedule deleted. Attendance records (if any) are preserved.', 'success')
    except Exception as e:
        db.session.rollback()
        print('Failed to delete schedule:', e)
        flash('Failed to delete schedule.', 'danger')

    return redirect(url_for('show_schedule', Standard=schedule.Standard))

@app.route("/schedule/<Standard>")
@login_required
def show_schedule(Standard):
    # Ensure expired schedules are removed before listing
    # remove_expired_schedules()
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    view_type = request.args.get('view', 'today')  # 'today', 'previous', 'upcoming'
    req_date = request.args.get('date')
    view_date = req_date or ''

    # Fetch student for layout header if user is a student
    student = None
    if session.get('role') == 'student':
        student_id = session.get('user')
        student = Student_reg.query.filter_by(Student_id=student_id).first()

    # Fetch all schedules for this standard (we will partition later)
    try:
        all_schedules = Schedule.query.filter(Schedule.Standard == Standard).order_by(Schedule.Date.asc(), Schedule.Start_time.asc()).all()
    except Exception:
        all_schedules = []

    # visibility rules: only root or specified users (adder/marker/allowed admins) can see a schedule
    user = session.get('user')
    role = session.get('role')

    def _visible(sch, user, role):
        if role in ['root', 'admin']:
            return True
        if not user:
            return False
        if getattr(sch, 'Added_by', None) == user:
            return True
        if getattr(sch, 'Marker', None) == user:
            return True
        allowed = (getattr(sch, 'Allowed_admins') or '')
        allowed_list = [a.strip() for a in allowed.split(',') if a.strip()]
        if user in allowed_list:
            return True
        return False

    visible_schedules = [s for s in all_schedules if _visible(s, user, role)]

    # partition schedules relative to today
    past = []
    today_list = []
    future = []
    for s in visible_schedules:
        try:
            sd = s.Date
            if isinstance(sd, str):
                sd_str = sd.split(' ')[0]
            else:
                sd_str = sd.strftime('%Y-%m-%d')
        except Exception:
            sd_str = ''

        if sd_str < today:
            past.append(s)
        elif sd_str == today:
            today_list.append(s)
        else:
            future.append(s)

    def build_info_list(schedule_list):
        info = []
        for s in schedule_list:
            entries = Attendence.query.filter_by(
                Class=Standard,
                Subject=s.Subject,
                Professor_name=s.Professor_name,
                Date=s.Date,
                Start_time=s.Start_time,
                End_time=s.End_time
            ).order_by(Attendence.Marked_at.desc()).all()
            attended = len(entries) > 0
            last_marked = entries[0].Marked_at if attended else None
            last_marked_by = entries[0].Marked_by if attended else None
            audits = ScheduleAudit.query.filter_by(schedule_id=s.Schedule_id).order_by(ScheduleAudit.timestamp.desc()).all()
            info.append({
                'schedule': s,
                'attended': attended,
                'last_marked': last_marked,
                'last_marked_by': last_marked_by,
                'audits': audits
            })
        return info

    past_info = build_info_list(past)
    today_info = build_info_list(today_list)
    future_info = build_info_list(future)

    # if specific date filter requested when viewing previous schedules, narrow past_info
    if view_type == 'previous' and view_date:
        past_info = [item for item in past_info if
                     (isinstance(item['schedule'].Date, str) and item['schedule'].Date.split(' ')[0] == view_date) or
                     (not isinstance(item['schedule'].Date, str) and item['schedule'].Date.strftime('%Y-%m-%d') == view_date)]

    # choose which list to display
    if view_type == 'previous':
        display_list = past_info
    elif view_type == 'upcoming':
        display_list = future_info
    else:
        display_list = today_info

    return render_template(
        "Schedule.html",
        Standard=Standard,
        view_type=view_type,
        view_date=view_date,
        schedules=display_list,
        student=student,
        parameters=parameters
    )


@app.route("/student_schedule")
@login_required
def student_schedule():
    """Show schedule for the logged-in student with Previous/Today/Upcoming views."""
    if session.get('role') != 'student':
        flash('Access denied. Student login required.', 'danger')
        return redirect(url_for('login'))
    
    student_id = session.get('user')
    student = Student_reg.query.filter_by(Student_id=student_id).first()
    
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('login'))
    
    # Get user's standard
    Standard = student.Standard
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    view_type = request.args.get('view', 'today')
    req_date = request.args.get('date')
    view_date = req_date or ''

    # Fetch all schedules for student's standard
    try:
        all_schedules = Schedule.query.filter(Schedule.Standard == Standard).order_by(Schedule.Date.asc(), Schedule.Start_time.asc()).all()
    except Exception:
        all_schedules = []

    # partition schedules relative to today
    past = []
    today_list = []
    future = []
    for s in all_schedules:
        try:
            sd = s.Date
            if isinstance(sd, str):
                sd_str = sd.split(' ')[0]
            else:
                sd_str = sd.strftime('%Y-%m-%d')
        except Exception:
            sd_str = ''

        if sd_str < today:
            past.append(s)
        elif sd_str == today:
            today_list.append(s)
        else:
            future.append(s)

    # if specific date filter requested when viewing previous schedules, narrow past
    if view_type == 'previous' and view_date:
        past = [s for s in past if
                (isinstance(s.Date, str) and s.Date.split(' ')[0] == view_date) or
                (not isinstance(s.Date, str) and s.Date.strftime('%Y-%m-%d') == view_date)]

    # choose which list to display
    if view_type == 'previous':
        display_list = past
    elif view_type == 'upcoming':
        display_list = future
    else:
        display_list = today_list

    return render_template(
        "student_schedule.html",
        Standard=Standard,
        view_type=view_type,
        view_date=view_date,
        schedules=display_list,
        student=student,
        parameters=parameters
    )


@app.route("/student_attendence/<int:student_id>")
@app.route("/student_attendence/<student_id>")
@login_required
def student_attendence(student_id):
    student = Student_reg.query.filter_by(Student_id=student_id).first()
    attendance_records = Attendence.query.filter_by(Student_id=student_id).order_by(Attendence.Date.desc()).all()
    attendance_start = attendance_records[-1].Date if attendance_records else None
    attendance_end = attendance_records[0].Date if attendance_records else None

    return render_template("student_attendence.html", student=student, attendance_records=attendance_records, attendance_start=attendance_start, attendance_end=attendance_end, parameters=parameters)


@app.route('/attendance')
@login_required
def attendance_batches():
    # Show all classes/batches for attendance
    classes = db.session.query(Student_reg.Standard, func.count(Student_reg.Sr_no)).group_by(Student_reg.Standard).all()
    classes = [(c[0], c[1]) for c in classes]
    return render_template('attendance_batches.html', classes=classes, parameters=parameters)


@app.route('/attendance/<Standard>')
@login_required
def attendance_schedules(Standard):
    # Show schedules for the selected class/batch
    # Students may only see today's and future schedules here; past schedules are accessed via attendance records
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    if session.get('role') == 'student':
        schedules = Schedule.query.filter(Schedule.Standard==Standard, Schedule.Date >= today).order_by(Schedule.Date.asc(), Schedule.Start_time.asc()).all()
    else:
        schedules = Schedule.query.filter_by(Standard=Standard).order_by(Schedule.Date.asc(), Schedule.Start_time.asc()).all()
        # Apply visibility: non-root users only see schedules they are allowed to view
        user = session.get('user')
        role = session.get('role')
        def _visible(sch, user, role):
            if role == 'root':
                return True
            if not user:
                return False
            if getattr(sch, 'Added_by', None) == user:
                return True
            if getattr(sch, 'Marker', None) == user:
                return True
            allowed = (getattr(sch, 'Allowed_admins') or '')
            allowed_list = [a.strip() for a in allowed.split(',') if a.strip()]
            if user in allowed_list:
                return True
            return False

        if role not in ['root', 'admin']:
            schedules = [s for s in schedules if _visible(s, user, role)]
    return render_template('attendance_schedules.html', Standard=Standard, schedules=schedules, parameters=parameters, today=today)


@app.route('/attendance/<Standard>/batches')
@login_required
def attendance_class_batches(Standard):
    # Show batches for a given Standard with counts and an All Students option
    batches = Batch.query.filter_by(Standard=Standard).order_by(Batch.Stream, Batch.name).all()
    # counts per batch
    batch_counts = []
    for b in batches:
        cnt = Student_reg.query.filter_by(Standard=Standard, Student_batch=b.name).count()
        batch_counts.append((b, cnt))
    # total students in class
    total = Student_reg.query.filter_by(Standard=Standard).count()
    return render_template('attendance_class_batches.html', Standard=Standard, batch_counts=batch_counts, total=total, parameters=parameters)


@app.route('/students/<Standard>')
@login_required
def students_of_class(Standard):
    # show all students for a Standard
    if Standard == 'ALL':
        students = Student_reg.query.order_by(Student_reg.Student_name.asc()).all()
    else:
        students = Student_reg.query.filter_by(Standard=Standard).order_by(Student_reg.Student_name.asc()).all()
    return render_template('Students.html', Standard=Standard, Students=students, parameters=parameters)


@app.route('/students/<Standard>/batch/<batch_name>')
@login_required
def students_of_batch(Standard, batch_name):
    students = Student_reg.query.filter_by(Standard=Standard, Student_batch=batch_name).order_by(Student_reg.Student_name.asc()).all()
    return render_template('Students.html', Standard=f"{Standard} - {batch_name}", Students=students, parameters=parameters)



@app.route('/attendance/<Standard>/<int:schedule_id>', methods=['GET', 'POST'])
@login_required
def attendance_take(Standard, schedule_id):
    # Show students for the class and allow marking attendance for the selected schedule
    students = Student_reg.query.filter_by(Standard=Standard).all()
    schedule = Schedule.query.filter_by(Schedule_id=schedule_id, Standard=Standard).first()
    if not schedule:
        flash('Schedule not found for this class.', 'danger')
        return redirect(url_for('attendance_schedules', Standard=Standard))

    # Check schedule date for attendance validation
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    schedule_date_str = schedule.Date.isoformat() if hasattr(schedule.Date, 'isoformat') else str(schedule.Date)
    is_today = schedule_date_str == today
    is_past = schedule_date_str < today
    is_future = schedule_date_str > today
    
    can_mark_new = is_today or is_past  # Can mark new attendance for today or past dates (if not yet marked)
    can_edit_existing = is_today or is_past  # Can edit existing attendance for today or past dates

    # Load existing attendance entries for this schedule (if any)
    try:
        existing_entries = Attendence.query.filter_by(
            Class=Standard,
            Subject=schedule.Subject,
            Professor_name=schedule.Professor_name,
            Date=schedule.Date,
            Start_time=schedule.Start_time,
            End_time=schedule.End_time
        ).all()
        existing_map = {e.Student_id: e for e in existing_entries}
    except OperationalError as oe:
        # Likely the DB schema hasn't been migrated to include Schedule_id/Marked_at
        # Fall back to a raw SQL query selecting known columns to avoid model mapping errors.
        print('OperationalError when querying Attendence (falling back):', oe)
        sql = text(
            "SELECT Attendence_id, Class, Subject, Professor_name, Student_id, Student_name, Date, Start_time, End_time, Status, Remark "
            "FROM attendence "
            "WHERE Class = :cls AND Subject = :sub AND Professor_name = :prof AND Date = :dt AND Start_time = :st AND End_time = :et"
        )
        conn = db.engine.connect()
        rows = conn.execute(sql, {
            'cls': Standard,
            'sub': schedule.Subject,
            'prof': schedule.Professor_name,
            'dt': schedule.Date,
            'st': schedule.Start_time,
            'et': schedule.End_time
        }).fetchall()
        conn.close()
        # Build lightweight objects (dict-like) to act as existing entries
        existing_map = {}
        for r in rows:
            # Use Row._mapping for a stable mapping interface across SQLAlchemy versions
            m = dict(r._mapping) if hasattr(r, '_mapping') else dict(r)
            sid = m.get('Student_id') or m.get('student_id') or None
            status = m.get('Status') or m.get('status') or None
            remark = m.get('Remark') or m.get('remark') or None
            if sid is None:
                # skip malformed rows
                continue
            existing_map[sid] = type('E', (), {
                'Student_id': sid,
                'Status': status,
                'Remark': remark,
                'Marked_at': None,
                'Marked_by': None
            })()

    # Prepare a map of student_id -> existing status/remark for the template.
    # This must be defined *before* any early returns in POST so that the
    # template rendering for error cases (e.g. future dates) does not raise
    # a NameError for an undefined `prefill` variable.
    prefill = {sid: {'Status': ent.Status, 'Remark': ent.Remark} for sid, ent in existing_map.items()}

    # Prepare date_info early so we can reuse it for error returns
    date_info = {
        'is_today': is_today,
        'is_past': is_past,
        'is_future': is_future,
        'can_mark_new': can_mark_new,
        'can_edit_existing': can_edit_existing,
        'schedule_date': schedule_date_str
    }

    # Detect read-only view mode when '?view=1' is present in URL
    read_only = bool(request.args.get('view'))

    # If opened in read-only mode, do not accept POST submissions
    if read_only and request.method == 'POST':
        return redirect(url_for('attendance_take', Standard=Standard, schedule_id=schedule_id))

    if request.method == 'POST':
        # Validate that ALL students have attendance marked (Present or Absent)
        unmarked_students = []
        for student in students:
            attendance_status = request.form.get(f'attendance_{student.Student_id}')
            if not attendance_status:
                unmarked_students.append(student.Student_name)
        
        if unmarked_students:
            flash(f'Please mark attendance for all students. Unmarked: {", ".join(unmarked_students)}', 'warning')
            return render_template('attendance_take.html', Standard=Standard, schedule=schedule, Students=students, prefill=prefill, parameters=parameters, date_info=date_info)
        # Block new attendance for future dates
        if is_future:
            flash('Cannot mark attendance for future schedules.', 'danger')
            return render_template('attendance_take.html', Standard=Standard, schedule=schedule, Students=students, prefill=prefill, parameters=parameters, error_msg='Attendance cannot be marked for future dates.')
        
        # Block editing if no existing record for future dates
        for student in students:
            attendance_status = request.form.get(f'attendance_{student.Student_id}')
            if attendance_status:
                # Check if trying to mark attendance for future (without existing record)
                if is_future and student.Student_id not in existing_map:
                    flash('Cannot mark new attendance for future schedules.', 'danger')
                    return render_template('attendance_take.html', Standard=Standard, schedule=schedule, Students=students, prefill=prefill, parameters=parameters, error_msg='Attendance cannot be marked for future dates.')
        
        for student in students:
            attendance_status = request.form.get(f'attendance_{student.Student_id}')
            reason = request.form.get(f'reason_{student.Student_id}', '')
            if attendance_status:
                if student.Student_id in existing_map:
                    # update existing record (allowed for today and past, not future)
                    if is_future:
                        continue  # Skip if future and trying to mark new
                    ent = existing_map[student.Student_id]
                    ent.Status = attendance_status
                    ent.Remark = reason
                    ent.Marked_at = datetime.datetime.now()
                    ent.Marked_by = session.get('user') if 'user' in session else None
                    db.session.add(ent)
                else:
                    # create new record linked to schedule (only for today and past)
                    if can_mark_new:
                        entry = Attendence(
                            Class=Standard,
                            Professor_name=schedule.Professor_name,
                            Subject=schedule.Subject,
                            Student_id=student.Student_id,
                            Student_name=student.Student_name,
                            Date=schedule.Date,
                            Start_time=schedule.Start_time,
                            End_time=schedule.End_time,
                            Status=attendance_status,
                            Remark=reason,
                            Schedule_id=schedule.Schedule_id,
                            Marked_at=datetime.datetime.now(),
                            Marked_by=session.get('user') if 'user' in session else None
                        )
                        db.session.add(entry)
            else:
                # if no value submitted and there is an existing entry, leave it unchanged
                pass

        db.session.commit()
        flash('Attendance saved for schedule.', 'success')
        # Re-query saved entries to build prefill for rendering (reflects saved values)
        try:
            saved_entries = Attendence.query.filter_by(
                Class=Standard,
                Subject=schedule.Subject,
                Professor_name=schedule.Professor_name,
                Date=schedule.Date,
                Start_time=schedule.Start_time,
                End_time=schedule.End_time
            ).all()
            prefill = {e.Student_id: {'Status': e.Status, 'Remark': e.Remark} for e in saved_entries}
        except Exception:
            # Fallback: reuse existing_map if re-query fails
            prefill = {sid: {'Status': ent.Status, 'Remark': ent.Remark} for sid, ent in existing_map.items()}

        # date_info already prepared above; reuse for post-submission render
        
        return render_template('attendance_take.html', Standard=Standard, schedule=schedule, Students=students, prefill=prefill, parameters=parameters, show_popup=True, date_info=date_info)

    # For initial GET requests, `prefill` has already been built above from
    # `existing_map`, so we just pass it through to the template here.

    # Pass date status and restrictions to template
    date_info = {
        'is_today': is_today,
        'is_past': is_past,
        'is_future': is_future,
        'can_mark_new': can_mark_new,
        'can_edit_existing': can_edit_existing,
        'schedule_date': schedule_date_str
    }
    
    return render_template('attendance_take.html', Standard=Standard, schedule=schedule, Students=students, prefill=prefill, parameters=parameters, date_info=date_info, read_only=read_only)


@app.route('/attendance/view/<Standard>/<int:schedule_id>')
@login_required
def attendance_view_read_only(Standard, schedule_id):
    # Read-only listing of attendance for a schedule
    schedule = Schedule.query.filter_by(Schedule_id=schedule_id, Standard=Standard).first()
    if not schedule:
        flash('Schedule not found for this class.', 'danger')
        return redirect(url_for('show_schedule', Standard=Standard))

    # Try to fetch by Schedule_id first
    try:
        entries = Attendence.query.filter_by(Schedule_id=schedule_id).order_by(Attendence.Student_name.asc()).all()
    except Exception:
        entries = Attendence.query.filter_by(Class=Standard, Subject=schedule.Subject, Date=schedule.Date, Start_time=schedule.Start_time, End_time=schedule.End_time).order_by(Attendence.Student_name.asc()).all()

    # Build list with student photo info
    out = []
    for e in entries:
        photo = None
        try:
            s = Student_reg.query.filter_by(Student_id=e.Student_id).first()
            if s:
                photo = s.Student_photo
        except Exception:
            photo = None
        out.append(type('R', (), {
            'Student_id': e.Student_id,
            'Student_name': e.Student_name,
            'Status': e.Status,
            'Remark': e.Remark,
            'photo': photo
        })())

    return render_template('attendence_view_read_only.html', Standard=Standard, schedule=schedule, entries=out, parameters=parameters)


# ==================== EXAM ROUTES ====================

@app.route('/exams')
@login_required
def exam_batches():
    """Show all class/batch options for exam management."""
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    classes = db.session.query(Student_reg.Standard, func.count(Student_reg.Sr_no)).group_by(Student_reg.Standard).all()
    classes = [(c[0], c[1]) for c in classes]
    return render_template('exam_batches.html', classes=classes, parameters=parameters)


@app.route('/exam/<Standard>')
@login_required
def exam_schedules(Standard):
    """Show exams for a selected class/batch, allowing navigation between past, today and upcoming."""
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    exams = Exam.query.filter_by(Standard=Standard).order_by(Exam.Date.asc()).all()
    today = datetime.date.today()
    past_exams = []
    today_exams = []
    upcoming_exams = []
    for e in exams:
        if isinstance(e.Date, datetime.datetime):
            d = e.Date.date()
        else:
            d = e.Date
        if d < today:
            past_exams.append(e)
        elif d == today:
            today_exams.append(e)
        else:
            upcoming_exams.append(e)

    view_type = request.args.get('view', 'today')
    req_date = request.args.get('date')
    view_date = req_date or ''

    # filter past_exams if specific date requested
    if view_type == 'previous' and view_date:
        past_exams = [ex for ex in past_exams if (isinstance(ex.Date, str) and ex.Date.split(' ')[0] == view_date) or
                      (not isinstance(ex.Date, str) and ex.Date.strftime('%Y-%m-%d') == view_date)]

    if view_type == 'previous':
        display = past_exams
    elif view_type == 'upcoming':
        display = upcoming_exams
    else:
        display = today_exams

    return render_template('exam_schedules.html', Standard=Standard,
                           exams=display,
                           view_type=view_type,
                           view_date=view_date,
                           parameters=parameters)


@app.route('/exams/<Standard>/batches')
@login_required
def exam_class_batches(Standard):
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    batches = Batch.query.filter_by(Standard=Standard).order_by(Batch.Stream, Batch.name).all()
    batch_counts = []
    for b in batches:
        cnt = Student_reg.query.filter_by(Standard=Standard, Student_batch=b.name).count()
        batch_counts.append((b, cnt))
    total = Student_reg.query.filter_by(Standard=Standard).count()
    return render_template('exam_class_batches.html', Standard=Standard, batch_counts=batch_counts, total=total, parameters=parameters)


@app.route('/exam/<int:exam_id>/attendance', methods=['GET', 'POST'])
@login_required
def exam_attendance(exam_id):
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied.', 'danger')
        return redirect(url_for('login'))

    exam = Exam.query.get_or_404(exam_id)

    # get students of that standard
    students = Student_reg.query.filter_by(Standard=exam.Standard).all()

    # load existing exam attendance (map by student id)
    existing_rows = ExamAttendance.query.filter_by(Exam_id=exam_id).order_by(ExamAttendance.Marked_at.desc()).all()
    existing_map = {r.Student_id: r for r in existing_rows}

    if request.method == 'POST':
        # Save or update attendance similarly to normal attendance design
        now = datetime.datetime.now()
        for stu in students:
            status = request.form.get(f"status_{stu.Student_id}")
            if status:
                existing = existing_map.get(stu.Student_id)
                if existing:
                    # update existing record
                    existing.Status = status
                    existing.Marked_at = now
                    db.session.add(existing)
                else:
                    # create new attendance record
                    record = ExamAttendance(
                        Exam_id=exam_id,
                        Student_id=stu.Student_id,
                        Student_name=stu.Student_name,
                        Status=status,
                        Marked_at=now
                    )
                    db.session.add(record)
        db.session.commit()

        flash("Attendance saved successfully!", "success")
        return redirect(url_for('exam_marks_entry', exam_id=exam_id))

    # prepare prefill map for template (student_id -> Status)
    prefill = {sid: {'Status': ent.Status} for sid, ent in existing_map.items()}

    return render_template(
        'exam_attendance.html',
        exam=exam,
        students=students,
        prefill=prefill,
        parameters=parameters
    )


# Consolidated marks entry handler is defined later as `exam_marks_entry`.
# The older `enter_exam_marks` block was removed to avoid duplicate endpoints
# and to keep endpoint names consistent with templates (`exam_marks_entry`).


@app.route('/add_exam', methods=['GET', 'POST'])
@login_required
def add_exam():
    """Create a new exam schedule."""
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    
    Standards = db.session.query(Student_reg.Standard).distinct().all()
    classes = [s[0] for s in Standards]
    
    if request.method == 'POST':
        standard = request.form.get('standard')
        subject = request.form.get('subject')
        date = request.form.get('date')
        start_hour = request.form.get('start_hour')
        start_minute = request.form.get('start_minute')
        start_period = request.form.get('start_period', 'AM')
        end_hour = request.form.get('end_hour')
        end_minute = request.form.get('end_minute')
        end_period = request.form.get('end_period', 'AM')
        total_marks = request.form.get('total_marks')
        professor_name = request.form.get('professor_name')
        
        # Format time display as HH:MM AM/PM
        display_start_time = f"{start_hour}:{start_minute} {start_period}" if start_hour and start_minute else ""
        display_end_time = f"{end_hour}:{end_minute} {end_period}" if end_hour and end_minute else ""
        
        try:
            exam = Exam(
                Date=date,
                Standard=standard,
                Subject=subject,
                Start_time=display_start_time,
                End_time=display_end_time,
                Total_marks=int(total_marks) if total_marks else None,
                Professor_name=professor_name
            )
            db.session.add(exam)
            db.session.commit()
            flash('Exam schedule added successfully!', 'success')
            return redirect(url_for('exam_schedules', Standard=standard))
        except Exception as e:
            db.session.rollback()
            print('Failed to add exam:', e)
            flash('Failed to add exam schedule.', 'danger')
    
    return render_template('add_exam.html', classes=classes, parameters=parameters)


@app.route('/edit_exam/<int:exam_id>', methods=['GET', 'POST'])
@login_required
def edit_exam(exam_id):
    """Edit an existing exam schedule."""
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    
    exam = Exam.query.filter_by(Exam_id=exam_id).first()
    if not exam:
        flash('Exam not found.', 'danger')
        return redirect(url_for('exam_batches'))
    
    Standards = db.session.query(Student_reg.Standard).distinct().all()
    classes = [s[0] for s in Standards]
    
    if request.method == 'POST':
        exam.Subject = request.form.get('subject')
        exam.Date = request.form.get('date')
        start_hour = request.form.get('start_hour')
        start_minute = request.form.get('start_minute')
        start_period = request.form.get('start_period', 'AM')
        end_hour = request.form.get('end_hour')
        end_minute = request.form.get('end_minute')
        end_period = request.form.get('end_period', 'AM')
        total_marks = request.form.get('total_marks')
        exam.Professor_name = request.form.get('professor_name')
        
        # Format time display as HH:MM AM/PM
        exam.Start_time = f"{start_hour}:{start_minute} {start_period}" if start_hour and start_minute else ""
        exam.End_time = f"{end_hour}:{end_minute} {end_period}" if end_hour and end_minute else ""
        exam.Total_marks = int(total_marks) if total_marks else None
        
        try:
            db.session.add(exam)
            db.session.commit()
            flash('Exam schedule updated successfully!', 'success')
            return redirect(url_for('exam_schedules', Standard=exam.Standard))
        except Exception as e:
            db.session.rollback()
            print('Failed to update exam:', e)
            flash('Failed to update exam schedule.', 'danger')
    
    return render_template('edit_exam.html', exam=exam, classes=classes, parameters=parameters)


@app.route('/delete_exam/<int:exam_id>', methods=['POST'])
@login_required
def delete_exam(exam_id):
    """Delete an exam schedule and associated marks."""
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    
    exam = Exam.query.filter_by(Exam_id=exam_id).first()
    if not exam:
        flash('Exam not found.', 'danger')
        return redirect(url_for('exam_batches'))
    
    try:
        # Delete associated marks
        ExamMarks.query.filter_by(Exam_id=exam_id).delete()
        db.session.delete(exam)
        db.session.commit()
        flash('Exam and associated marks deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        print('Failed to delete exam:', e)
        flash('Failed to delete exam.', 'danger')
    
    return redirect(url_for('exam_schedules', Standard=exam.Standard))


@app.route('/exam/<int:exam_id>/marks', methods=['GET', 'POST'])
@login_required
def exam_marks_entry(exam_id):
    """Enter/edit student marks for an exam."""
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    
    exam = Exam.query.filter_by(Exam_id=exam_id).first()
    if not exam:
        flash('Exam not found.', 'danger')
        return redirect(url_for('exam_batches'))
    
    # Prefer to show only students who were present in the exam (based on ExamAttendance)
    # Get latest present attendance rows ordered by Marked_at desc so we dedupe
    attendance_rows = ExamAttendance.query.filter(ExamAttendance.Exam_id == exam_id, ExamAttendance.Status.ilike('present')).order_by(ExamAttendance.Marked_at.desc()).all()
    present_map = {}
    for r in attendance_rows:
        if r.Student_id not in present_map:
            present_map[r.Student_id] = r

    # Build list of Student_reg objects for present students preserving the order seen in present_map
    present_students = []
    if present_map:
        for sid in present_map.keys():
            s = Student_reg.query.filter_by(Student_id=sid).first()
            if s:
                present_students.append(s)
    else:
        # Fallback: if no attendance records, show all students in the class
        present_students = Student_reg.query.filter_by(Standard=exam.Standard).all()

    # Get existing marks for this exam and map by Student_id
    existing_marks = ExamMarks.query.filter_by(Exam_id=exam_id).all()
    marks_map = {m.Student_id: m for m in existing_marks}

    if request.method == 'POST':
        for student in present_students:
            marks = request.form.get(f'marks_{student.Student_id}')
            remarks = request.form.get(f'remark_{student.Student_id}', '')

            if marks:  # Only save if marks provided
                try:
                    marks_float = float(marks)
                    if student.Student_id in marks_map:
                        # Update existing
                        mrec = marks_map[student.Student_id]
                        mrec.Marks_obtained = marks_float
                        mrec.Remarks = remarks
                        mrec.Entered_by = session.get('user')
                        mrec.Entered_at = datetime.datetime.now()
                        db.session.add(mrec)
                    else:
                        # Create new
                        mark_record = ExamMarks(
                            Exam_id=exam_id,
                            Student_id=student.Student_id,
                            Student_name=student.Student_name,
                            Marks_obtained=marks_float,
                            Remarks=remarks,
                            Entered_by=session.get('user'),
                            Entered_at=datetime.datetime.now()
                        )
                        db.session.add(mark_record)
                except ValueError:
                    flash(f'Invalid marks for {student.Student_name}. Skipped.', 'warning')

        try:
            db.session.commit()
            # Recompute and persist exam-specific ranks so UI reflects updates
            try:
                update_exam_ranks(exam_id)
            except Exception:
                pass
            flash('Marks saved successfully!', 'success')
            return redirect(url_for('exam_marks_view', exam_id=exam_id))
        except Exception as e:
            db.session.rollback()
            print('Failed to save marks:', e)
            flash('Failed to save marks.', 'danger')

    # Prepare prefill data
    prefill = {sid: {'marks': m.Marks_obtained, 'remarks': m.Remarks} for sid, m in marks_map.items()}

    return render_template('exam_marks_entry.html', exam=exam, present_students=present_students, prefill=prefill, parameters=parameters)


@app.route('/exam/<int:exam_id>/marks/view', methods=['GET'])
@login_required
def exam_marks_view(exam_id):
    """View saved marks for an exam with option to edit."""
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    
    exam = Exam.query.filter_by(Exam_id=exam_id).first()
    if not exam:
        flash('Exam not found.', 'danger')
        return redirect(url_for('exam_batches'))
    
    # Get all saved marks for this exam, sorted by student name
    saved_marks = ExamMarks.query.filter_by(Exam_id=exam_id).order_by(ExamMarks.Student_name.asc()).all()
    
    if not saved_marks:
        flash('No marks recorded for this exam yet.', 'info')
        return redirect(url_for('exam_marks_entry', exam_id=exam_id))
    
    return render_template('exam_marks_view.html', exam=exam, saved_marks=saved_marks, parameters=parameters)


# ==================== HELPER FUNCTIONS FOR STUDENT PERFORMANCE ====================

def calculate_class_rankings(standard, exam_id=None):
    """
    Calculate rankings for students in a class based on exam marks.
    If exam_id is None, calculates based on average/total marks across all exams.
    
    Args:
        standard: Class/Standard string (e.g., '10th')
        exam_id: Optional exam ID for exam-specific ranking
    
    Returns:
        Dict mapping Student_id -> {'rank': rank, 'total_marks': marks, 'student_count': count}
    """
    # Get all students in the class
    students = Student_reg.query.filter_by(Standard=standard).all()
    if not students:
        return {}
    
    student_marks = {}
    
    if exam_id:
        # Exam-specific ranking
        for student in students:
            mark = ExamMarks.query.filter_by(Exam_id=exam_id, Student_id=student.Student_id).first()
            if mark and mark.Marks_obtained is not None:
                student_marks[student.Student_id] = float(mark.Marks_obtained)
    else:
        # Overall ranking (average marks across all exams)
        for student in students:
            marks = ExamMarks.query.filter_by(Student_id=student.Student_id).all()
            if marks:
                total = sum([m.Marks_obtained for m in marks if m.Marks_obtained is not None])
                count = len([m for m in marks if m.Marks_obtained is not None])
                if count > 0:
                    student_marks[student.Student_id] = total / count  # Average
    
    if not student_marks:
        return {}
    
    # Sort by marks descending and assign ranks (handle ties)
    sorted_marks = sorted(student_marks.items(), key=lambda x: x[1], reverse=True)
    rankings = {}
    current_rank = 1
    prev_marks = None
    
    for idx, (student_id, marks) in enumerate(sorted_marks):
        # If marks are different, update rank; if same, keep previous rank
        if prev_marks is not None and marks < prev_marks:
            current_rank = idx + 1
        rankings[student_id] = {
            'rank': current_rank,
            'total_marks': marks,
            'student_count': len(student_marks)
        }
        prev_marks = marks
    
    return rankings


def update_exam_ranks(exam_id):
    """Recalculate and persist exam-specific rankings into `ExamRank` table.

    This ensures ranks immediately reflect any mark edits.
    """
    try:
        exam = Exam.query.filter_by(Exam_id=exam_id).first()
        if not exam:
            return
        # compute rankings
        rankings = calculate_class_rankings(exam.Standard, exam_id=exam_id)

        # remove existing cached ranks for this exam
        ExamRank.query.filter_by(Exam_id=exam_id).delete()

        # insert new ranks
        for student_id, data in rankings.items():
            m = ExamMarks.query.filter_by(Exam_id=exam_id, Student_id=student_id).first()
            marks_val = float(m.Marks_obtained) if (m and m.Marks_obtained is not None) else None
            perc = calculate_percentage(marks_val, exam.Total_marks) if marks_val is not None else None
            er = ExamRank(Exam_id=exam_id, Student_id=student_id, Rank=data['rank'], Marks=marks_val, Percentage=perc)
            db.session.add(er)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print('Failed to update exam ranks:', e)


def calculate_percentage(obtained_marks, total_marks):
    """Calculate percentage from obtained and total marks."""
    if total_marks is None or total_marks == 0:
        return 0
    try:
        total = float(total_marks) if isinstance(total_marks, str) else total_marks
        obtained = float(obtained_marks) if isinstance(obtained_marks, str) else obtained_marks
        return round((obtained / total) * 100, 2)
    except (ValueError, TypeError):
        return 0


@app.route('/student/performance')
@login_required
def student_performance():
    if session.get('role') != 'student':
        flash("Student access required!", "warning")
        return redirect(url_for('login'))

    sid = session.get("user")  # student_id stored in session
    student = Student_reg.query.filter_by(Student_id=sid).first()
    
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('login'))

    # Get all exam marks for this student
    exam_marks_data = (db.session.query(
                ExamMarks,
                Exam
            )
            .join(Exam, ExamMarks.Exam_id == Exam.Exam_id)
            .filter(ExamMarks.Student_id == sid)
            .order_by(Exam.Date.desc())
            .all())
    
    # Build performance data with percentage and details
    performance_list = []
    total_marks_obtained = 0
    total_marks_max = 0
    
    for mark, exam in exam_marks_data:
        if mark.Marks_obtained is not None:
            percentage = calculate_percentage(mark.Marks_obtained, exam.Total_marks)
            total_marks_obtained += mark.Marks_obtained
            if exam.Total_marks:
                try:
                    total_marks_max += float(exam.Total_marks)
                except (ValueError, TypeError):
                    pass  # Skip if conversion fails
            
            performance_list.append({
                'exam_id': exam.Exam_id,
                'subject': exam.Subject,
                'date': exam.Date,
                'marks_obtained': mark.Marks_obtained,
                'total_marks': exam.Total_marks,
                'percentage': percentage,
                'remarks': mark.Remarks
            })
    
    # Calculate overall percentage
    overall_percentage = calculate_percentage(total_marks_obtained, total_marks_max) if total_marks_max > 0 else 0
    
    # Get class-wide ranking (overall)
    class_rankings = calculate_class_rankings(student.Standard, exam_id=None)
    student_rank_info = class_rankings.get(sid, {'rank': 'N/A', 'total_marks': 0, 'student_count': 0})

    return render_template(
        "student_performance.html",
        student=student,
        performance_list=performance_list,
        total_marks_obtained=total_marks_obtained,
        total_marks_max=total_marks_max,
        overall_percentage=overall_percentage,
        rank_info=student_rank_info,
        parameters=parameters
    )


@app.route('/student/performance/<int:exam_id>')
@login_required
def student_exam_detail(exam_id):
    """Show detailed performance for a specific exam."""
    if session.get('role') != 'student':
        flash("Student access required!", "warning")
        return redirect(url_for('login'))

    sid = session.get("user")
    student = Student_reg.query.filter_by(Student_id=sid).first()
    
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('login'))
    
    # Get exam and student's marks
    exam = Exam.query.filter_by(Exam_id=exam_id).first()
    if not exam:
        flash('Exam not found.', 'danger')
        return redirect(url_for('student_performance'))
    
    # Get student's marks for this exam
    mark = ExamMarks.query.filter_by(Exam_id=exam_id, Student_id=sid).first()
    if not mark:
        flash('No marks recorded for this exam.', 'danger')
        return redirect(url_for('student_performance'))
    
    # Calculate percentage
    percentage = calculate_percentage(mark.Marks_obtained, exam.Total_marks) if mark.Marks_obtained else 0
    
    # Prefer cached ExamRank entries if available (updated after marks edits)
    ranks = ExamRank.query.filter_by(Exam_id=exam_id).order_by(ExamRank.Rank.asc()).all()
    all_rankings = []
    student_rank_info = {'rank': 'N/A', 'total_marks': 0, 'student_count': 0}
    if ranks:
        for r in ranks:
            st = Student_reg.query.filter_by(Student_id=r.Student_id).first()
            if st:
                all_rankings.append({
                    'rank': r.Rank,
                    'student_name': st.Student_name,
                    'student_id': r.Student_id,
                    'marks': r.Marks,
                    'percentage': r.Percentage
                })
        # find this student's rank
        me = next((x for x in all_rankings if x['student_id'] == sid), None)
        if me:
            student_rank_info = {'rank': me['rank'], 'total_marks': me.get('marks', 0), 'student_count': len(all_rankings)}
    else:
        # fallback to dynamic calculation
        class_rankings = calculate_class_rankings(student.Standard, exam_id=exam_id)
        student_rank_info = class_rankings.get(sid, {'rank': 'N/A', 'total_marks': 0, 'student_count': 0})
        for student_id, rank_data in sorted(class_rankings.items(), key=lambda x: x[1]['rank']):
            st = Student_reg.query.filter_by(Student_id=student_id).first()
            if st:
                m = ExamMarks.query.filter_by(Exam_id=exam_id, Student_id=student_id).first()
                if m and m.Marks_obtained is not None:
                    all_rankings.append({
                        'rank': rank_data['rank'],
                        'student_name': st.Student_name,
                        'student_id': st.Student_id,
                        'marks': m.Marks_obtained,
                        'percentage': calculate_percentage(m.Marks_obtained, exam.Total_marks)
                    })

    return render_template(
        "student_exam_detail.html",
        student=student,
        exam=exam,
        mark=mark,
        percentage=percentage,
        rank_info=student_rank_info,
        all_rankings=all_rankings,
        parameters=parameters
    )


# ==================== ADMIN/ROOT PERFORMANCE ANALYTICS ====================

@app.route('/admin/performance')
@login_required
def admin_performance():
    """Admin/Root view: All classes with performance overview."""
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    
    # Get all classes
    classes = db.session.query(Student_reg.Standard, func.count(Student_reg.Sr_no)).group_by(Student_reg.Standard).all()
    classes = [(c[0], c[1]) for c in classes]
    
    # Calculate performance stats for each class
    class_stats = []
    for standard, student_count in classes:
        students = Student_reg.query.filter_by(Standard=standard).all()
        
        # Get all marks for students in this class
        marks_data = db.session.query(ExamMarks).filter(
            ExamMarks.Student_id.in_([s.Student_id for s in students])
        ).all()
        
        if marks_data:
            total_exams = len(set([m.Exam_id for m in marks_data]))
            avg_marks = sum([m.Marks_obtained for m in marks_data if m.Marks_obtained]) / len([m for m in marks_data if m.Marks_obtained]) if marks_data else 0
            class_stats.append({
                'standard': standard,
                'student_count': student_count,
                'exam_count': total_exams,
                'avg_marks': round(avg_marks, 2)
            })
        else:
            class_stats.append({
                'standard': standard,
                'student_count': student_count,
                'exam_count': 0,
                'avg_marks': 0
            })
    
    return render_template('admin_performance.html', class_stats=class_stats, parameters=parameters)


@app.route('/admin/performance/<Standard>')
@login_required
def admin_class_performance(Standard):
    """Admin/Root view: All students in a class with rankings and performance."""
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    
    # Get all students in the class
    students = Student_reg.query.filter_by(Standard=Standard).all()
    
    if not students:
        flash('No students found in this standard.', 'danger')
        return redirect(url_for('admin_performance'))
    
    # Get performance data for all students
    student_performance_data = []
    
    for student in students:
        exam_marks = ExamMarks.query.filter_by(Student_id=student.Student_id).all()
        
        if exam_marks:
            total_obtained = sum([m.Marks_obtained for m in exam_marks if m.Marks_obtained])
            exam_count = len(exam_marks)
            avg_marks = total_obtained / exam_count if exam_count > 0 else 0
            
            student_performance_data.append({
                'student': student,
                'exam_count': exam_count,
                'avg_marks': round(avg_marks, 2),
                'total_obtained': round(total_obtained, 2)
            })
    
    # Calculate rankings
    class_rankings = calculate_class_rankings(Standard, exam_id=None)
    
    # Add rankings to student data
    for perf in student_performance_data:
        rank_info = class_rankings.get(perf['student'].Student_id, {'rank': 'N/A'})
        perf['rank'] = rank_info['rank']
    
    # Sort by rank
    student_performance_data.sort(key=lambda x: x['rank'] if isinstance(x['rank'], int) else float('inf'))
    
    return render_template('admin_class_performance.html', 
                         standard=Standard, 
                         student_performance_data=student_performance_data,
                         total_students=len(students),
                         parameters=parameters)


@app.route('/admin/student/<student_id>/performance')
@login_required
def admin_student_performance(student_id):
    """Admin/Root view: Detailed performance for a specific student."""
    if session.get('role') not in ['admin', 'root']:
        flash('Access denied. Admin or Root required.', 'danger')
        return redirect(url_for('login'))
    
    student = Student_reg.query.filter_by(Student_id=student_id).first()
    
    if not student:
        flash('Student not found.', 'danger')
        return redirect(url_for('admin_performance'))
    
    # Get all exam marks for this student
    exam_marks_data = (db.session.query(ExamMarks, Exam)
                      .join(Exam, ExamMarks.Exam_id == Exam.Exam_id)
                      .filter(ExamMarks.Student_id == student_id)
                      .order_by(Exam.Date.desc())
                      .all())
    
    # Build performance list
    performance_list = []
    total_marks_obtained = 0
    total_marks_max = 0
    
    for mark, exam in exam_marks_data:
        if mark.Marks_obtained is not None:
            percentage = calculate_percentage(mark.Marks_obtained, exam.Total_marks)
            total_marks_obtained += mark.Marks_obtained
            if exam.Total_marks:
                try:
                    total_marks_max += float(exam.Total_marks)
                except (ValueError, TypeError):
                    pass
            
            performance_list.append({
                'exam_id': exam.Exam_id,
                'subject': exam.Subject,
                'date': exam.Date,
                'marks_obtained': mark.Marks_obtained,
                'total_marks': exam.Total_marks,
                'percentage': percentage,
                'remarks': mark.Remarks
            })
    
    # Calculate overall percentage
    overall_percentage = calculate_percentage(total_marks_obtained, total_marks_max) if total_marks_max > 0 else 0
    
    # Get class rankings
    class_rankings = calculate_class_rankings(student.Standard, exam_id=None)
    rank_info = class_rankings.get(student_id, {'rank': 'N/A', 'total_marks': 0, 'student_count': 0})
    
    return render_template('admin_student_performance.html',
                         student=student,
                         performance_list=performance_list,
                         total_marks_obtained=total_marks_obtained,
                         total_marks_max=total_marks_max,
                         overall_percentage=overall_percentage,
                         rank_info=rank_info,
                         parameters=parameters)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # Auto-detect role and authenticate.
        # 1) Root (credentials stored in config.json)
        if username == parameters.get('Admin_user') and password == parameters.get('Admin_password'):
            session['user'] = username
            session['role'] = 'root'
            # Upsert a Login row for root so we can record last_login (store hashed for root)
            try:
                lr = Login.query.filter_by(account_id=username).first()
                now = datetime.datetime.now()
                if lr:
                    lr.last_login = now
                    lr.password = generate_password_hash(password)
                    lr.role = 'root'
                    db.session.add(lr)
                else:
                    hashed = generate_password_hash(password)
                    new_lr = Login(account_id=username, password=hashed, role='root', last_login=now)
                    db.session.add(new_lr)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print('Failed to upsert root login row:', e)
            return redirect(url_for('root_dashboard'))

        # 2) Try centralized Login table first (supports hashed or plaintext stored there)
        login_row = Login.query.filter_by(account_id=username).first()
        if login_row:
            authenticated = False
            try:
                # support plaintext match or hashed password
                if login_row.password == password:
                    authenticated = True
                else:
                    authenticated = check_password_hash(login_row.password, password)
            except Exception:
                authenticated = False

            if authenticated:
                session['user'] = login_row.account_id
                session['role'] = login_row.role
                try:
                    login_row.last_login = datetime.datetime.now()
                    db.session.add(login_row)
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    print('Failed to update last_login for', login_row.account_id, e)

                if login_row.role == 'admin':
                    return redirect(url_for('admin_profile', admin_id=login_row.account_id))
                elif login_row.role == 'student':
                    return redirect(url_for('student_notifications'))
                elif login_row.role == 'root':
                    return redirect(url_for('root_dashboard'))

        # 3) If no Login row or password didn't match, try Admin table directly
        admin = Admin.query.filter_by(Admin_id=username).first()
        if admin and getattr(admin, 'Password', None) == password:
            # create/update Login row for admin with hashed password
            try:
                now = datetime.datetime.now()
                hashed = generate_password_hash(password)
                lr = Login.query.filter_by(account_id=admin.Admin_id).first()
                if lr:
                    lr.password = hashed
                    lr.role = 'admin'
                    lr.last_login = now
                    db.session.add(lr)
                else:
                    new_lr = Login(account_id=admin.Admin_id, password=hashed, role='admin', last_login=now)
                    db.session.add(new_lr)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print('Failed to upsert admin login row:', e)

            session['user'] = admin.Admin_id
            session['role'] = 'admin'
            return redirect(url_for('admin_profile', admin_id=admin.Admin_id))

        # 4) Try Student table
        student = Student_reg.query.filter_by(Student_id=username).first()
        if student and getattr(student, 'Student_password', None) == password:
            # create/update Login row for student with hashed password (store plain password in Student_reg remains for display)
            try:
                now = datetime.datetime.now()
                hashed = generate_password_hash(password)
                lr = Login.query.filter_by(account_id=student.Student_id).first()
                if lr:
                    lr.password = hashed
                    lr.role = 'student'
                    lr.last_login = now
                    db.session.add(lr)
                else:
                    new_lr = Login(account_id=student.Student_id, password=hashed, role='student', last_login=now)
                    db.session.add(new_lr)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print('Failed to upsert student login row:', e)

            session['user'] = student.Student_id
            session['role'] = 'student'
            return redirect(url_for('student_dashboard'))

        # If nothing matched, show invalid credentials
        flash('Invalid credentials. Please try again.', 'danger')
    return render_template("login.html", parameters=parameters)



@app.route("/logout")
def logout():
    """Clear session and redirect to login."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


if __name__ == "__main__":
    app.run(debug=True)