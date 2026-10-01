import os
import sqlite3
import hashlib
from flask import Flask, render_template, request, send_file, session, redirect
from flask import Response
from pypdf import PdfWriter, PdfReader
from io import BytesIO
from PIL import Image

app = Flask(__name__)
app.secret_key = "edukit-v2-local-key"

# ==================== EDUKIT USER MANAGEMENT ====================
EDUKIT_USER_DB = os.path.join(app.root_path, "edukit_users.db")

def get_db():
    db = sqlite3.connect(EDUKIT_USER_DB)
    db.row_factory = sqlite3.Row
    return db

def init_user_db():
    db = get_db()
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            email TEXT DEFAULT '',
            role TEXT NOT NULL DEFAULT 'Student',
            access INTEGER NOT NULL DEFAULT 1,
            password_hash TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Upgrade older EduKit databases that do not yet have password_hash.
    cols = [row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()]
    if "password_hash" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
    db.commit()
    db.close()

init_user_db()

def admin_required():
    return bool(session.get("admin_logged_in"))






# ==================== EDUKIT ADMIN LOGIN ====================
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = hashlib.sha256("EduKit@123".encode("utf-8")).hexdigest()




def ensure_password_column():
    db = get_db()
    cols = [row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()]
    if "password_hash" not in cols:
        db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")
        db.commit()
    db.close()


@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not name or not username or not password:
            error = "Name, username and password are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            db = get_db()
            existing = db.execute(
                "SELECT id FROM users WHERE username=?", (username,)
            ).fetchone()
            if existing:
                db.close()
                error = "Username already exists."
            else:
                try:
                    password_hash = hashlib.sha256(
                        password.encode("utf-8")
                    ).hexdigest()
                    db.execute(
                        """INSERT INTO users
                           (name, username, email, role, access, password_hash)
                           VALUES (?, ?, ?, 'Student', 1, ?)""",
                        (name, username, email, password_hash)
                    )
                    db.commit()
                    db.close()
                    return redirect("/login")
                except Exception:
                    db.rollback()
                    db.close()
                    error = "Could not create the account."

    return render_template("signup.html", error=error)

@app.route("/student/dashboard")
def student_dashboard():
    if not session.get("user_id"):
        return redirect("/login")

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    db.close()

    if not user or not user["access"]:
        session.clear()
        return redirect("/login")

    return render_template("student_dashboard.html", user=user)


@app.route("/student/profile", methods=["GET", "POST"])
def student_profile():
    if not session.get("user_id"):
        return redirect("/login")

    message = None
    error = None

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

    if not user or not user["access"]:
        db.close()
        session.clear()
        return redirect("/login")

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()

        if not name:
            error = "Name cannot be empty."
        else:
            db.execute(
                "UPDATE users SET name=?, email=? WHERE id=?",
                (name, email, session["user_id"])
            )
            db.commit()
            message = "Profile updated successfully."
            user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]

    db.close()
    return render_template("student_profile.html", user=user, message=message, error=error)


@app.route("/student/change-password", methods=["POST"])
def student_change_password():
    if not session.get("user_id"):
        return redirect("/login")

    current = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()

    if not user:
        db.close()
        session.clear()
        return redirect("/login")

    if hashlib.sha256(current.encode("utf-8")).hexdigest() != user["password_hash"]:
        db.close()
        return redirect("/student/profile?password_error=Current+password+is+incorrect")

    if len(new_password) < 6 or new_password != confirm:
        db.close()
        return redirect("/student/profile?password_error=New+password+must+match+and+be+at+least+6+characters")

    db.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (hashlib.sha256(new_password.encode("utf-8")).hexdigest(), session["user_id"])
    )
    db.commit()
    db.close()
    return redirect("/student/profile?password_changed=1")


@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    if not admin_required():
        return redirect("/admin/login")

    # Never allow the currently logged-in admin to delete their own account.
    if session.get("admin_id") == user_id:
        return redirect("/admin?error=You+cannot+delete+your+own+admin+account")

    db = get_db()
    try:
        db.execute("DELETE FROM users WHERE id=?", (user_id,))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    return redirect("/admin?deleted=1")

@app.route("/admin/users/save", methods=["POST"])
def admin_user_save():
    if not admin_required():
        return redirect("/admin/login")

    user_id = request.form.get("user_id", "").strip()
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    role = request.form.get("role", "Student").strip()
    password = request.form.get("password", "")

    if not name or not username:
        return redirect("/admin?error=Name+and+username+are+required")
    if not user_id and len(password) < 6:
        return redirect("/admin?error=Password+must+be+at+least+6+characters")

    db = get_db()
    try:
        if user_id:
            if password:
                db.execute(
                    "UPDATE users SET name=?, username=?, email=?, role=?, password_hash=? WHERE id=?",
                    (name, username, email, role,
                     hashlib.sha256(password.encode("utf-8")).hexdigest(), int(user_id))
                )
            else:
                db.execute(
                    "UPDATE users SET name=?, username=?, email=?, role=? WHERE id=?",
                    (name, username, email, role, int(user_id))
                )
        else:
            db.execute(
                "INSERT INTO users (name, username, email, role, access, password_hash) VALUES (?, ?, ?, ?, 1, ?)",
                (name, username, email, role,
                 hashlib.sha256(password.encode("utf-8")).hexdigest())
            )
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        return redirect("/admin?error=Could+not+save+user")
    db.close()
    return redirect("/admin?saved=1")


@app.route("/admin/users/toggle/<int:user_id>", methods=["POST"])
def admin_user_toggle(user_id):
    if not admin_required():
        return redirect("/admin/login")

    db = get_db()
    db.execute(
        "UPDATE users SET access = CASE WHEN access=1 THEN 0 ELSE 1 END WHERE id=?",
        (user_id,)
    )
    db.commit()
    db.close()
    return redirect("/admin?access_updated=1")


@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
def admin_user_delete(user_id):
    if not admin_required():
        return redirect("/admin/login")

    db = get_db()
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    db.close()
    return redirect("/admin?deleted=1")


@app.route("/admin/users")
def admin_users():
    if not admin_required():
        return redirect("/admin/login")

    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    db.close()
    return render_template("admin_users.html", users=users)


@app.route("/login", methods=["GET", "POST"])
def user_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        db.close()

        if not user:
            error = "Invalid username or password."
        elif not bool(user["access"]):
            error = "Your account has been disabled by the administrator."
        else:
            stored = user["password_hash"] if "password_hash" in user.keys() else ""
            supplied = hashlib.sha256(password.encode("utf-8")).hexdigest()
            if not stored or supplied != stored:
                error = "Invalid username or password."
            else:
                session["user_id"] = user["id"]
                session["user_name"] = user["name"]
                session["user_username"] = user["username"]
                session["user_email"] = user["email"]
                session["user_role"] = user["role"]
                return redirect("/student/dashboard")

    return render_template("user_login.html", error=error)


@app.route("/logout")
def user_logout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("user_role", None)
    return redirect("/login")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and hashlib.sha256(password.encode("utf-8")).hexdigest() == ADMIN_PASSWORD_HASH:
            session["admin_logged_in"] = True
            return redirect("/admin")
        error = "Invalid username or password."
    return render_template("admin_login.html", error=error)

@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    total_users = db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    active_users = db.execute("SELECT COUNT(*) AS n FROM users WHERE access=1").fetchone()["n"]
    blocked_users = db.execute("SELECT COUNT(*) AS n FROM users WHERE access=0").fetchone()["n"]
    db.close()

    return render_template(
        "admin.html",
        users=users,
        total_users=total_users,
        active_users=active_users,
        blocked_users=blocked_users,
        saved=request.args.get("saved"),
        access_updated=request.args.get("access_updated"),
        deleted=request.args.get("deleted"),
        error=request.args.get("error")
    )

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect("/admin/login")
# ============================================================
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/tools")
def tools():
    return render_template("index.html")

@app.route("/profile", methods=["GET", "POST"])
def profile():
    if request.method == "POST":
        profile_data = {
            "name": request.form.get("name", "").strip(),
            "course": request.form.get("course", "").strip(),
            "college": request.form.get("college", "").strip(),
            "semester": request.form.get("semester", "").strip()
        }
        session["profile"] = profile_data
        return render_template("profile.html", profile=profile_data, saved=True)
    return render_template("profile.html", profile=session.get("profile", {}), saved=False)


@app.route("/dashboard")
def dashboard():
    results = session.get("results", {})
    activity = session.get("activity", [])
    profile = session.get("profile", {})
    return render_template(
        "dashboard.html",
        cgpa=results.get("cgpa"),
        percentage=results.get("percentage"),
        attendance=results.get("attendance"),
        activity=activity,
        profile=profile
    )



@app.route("/cgpa", methods=["GET", "POST"])
def cgpa():
    result = None
    error = None
    if request.method == "POST":
        try:
            grades = [float(x.strip()) for x in request.form.get("grades", "").split(",") if x.strip()]
            if not grades:
                error = "Please enter at least one grade point."
            elif any(x < 0 or x > 10 for x in grades):
                error = "Grade points should be between 0 and 10."
            else:
                result = round(sum(grades) / len(grades), 2)
                results = session.get("results", {})
                results["cgpa"] = result
                session["results"] = results
                activity = session.get("activity", [])
                activity.insert(0, f"CGPA calculated — {result}")
                session["activity"] = activity[:8]
        except ValueError:
            error = "Please enter valid numbers."
    return render_template("cgpa.html", result=result, error=error)


@app.route("/percentage", methods=["GET", "POST"])
def percentage():
    result = None
    error = None
    if request.method == "POST":
        try:
            obtained = float(request.form["obtained"])
            total = float(request.form["total"])
            if total <= 0:
                error = "Total marks must be greater than 0."
            elif obtained < 0 or obtained > total:
                error = "Obtained marks must be between 0 and total marks."
            else:
                result = round((obtained / total) * 100, 2)
                results = session.get("results", {})
                results["percentage"] = result
                session["results"] = results
                activity = session.get("activity", [])
                activity.insert(0, f"Percentage calculated — {result}%")
                session["activity"] = activity[:8]
        except ValueError:
            error = "Please enter valid numbers."
    return render_template("percentage.html", result=result, error=error)


@app.route("/attendance", methods=["GET", "POST"])
def attendance():
    result = None
    error = None
    if request.method == "POST":
        try:
            attended = float(request.form["attended"])
            conducted = float(request.form["conducted"])
            if conducted <= 0:
                error = "Total classes must be greater than 0."
            elif attended < 0 or attended > conducted:
                error = "Attended classes must be between 0 and total classes."
            else:
                result = round((attended / conducted) * 100, 2)
                results = session.get("results", {})
                results["attendance"] = result
                session["results"] = results
                activity = session.get("activity", [])
                activity.insert(0, f"Attendance calculated — {result}%")
                session["activity"] = activity[:8]
        except ValueError:
            error = "Please enter valid numbers."
    return render_template("attendance.html", result=result, error=error)


@app.route("/qr")
def qr():
    return render_template("qr.html")


@app.route("/pdf")
def pdf():
    return render_template("pdf.html")


@app.route("/merge-pdf", methods=["POST"])
def merge_pdf():
    files = request.files.getlist("pdfs")

    if len(files) < 2:
        return "Please select at least two PDF files.", 400

    writer = PdfWriter()

    try:
        for file in files:
            if not file.filename.lower().endswith(".pdf"):
                return "Only PDF files are allowed.", 400
            writer.append(file)

        output = BytesIO()
        writer.write(output)
        writer.close()
        output.seek(0)

        return send_file(
            output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="EduKit_Merged.pdf"
        )

    except Exception as e:
        return f"Could not merge the PDFs: {e}", 400


@app.route("/split-pdf", methods=["POST"])
def split_pdf():
    file = request.files.get("pdf")
    page = request.form.get("page", "").strip()

    if not file or not file.filename.lower().endswith(".pdf"):
        return "Please select a PDF file.", 400

    try:
        reader = PdfReader(file)
        total = len(reader.pages)

        if not page.isdigit() or not (1 <= int(page) <= total):
            return f"Enter a page number from 1 to {total}.", 400

        index = int(page) - 1
        writer = PdfWriter()
        writer.add_page(reader.pages[index])

        output = BytesIO()
        writer.write(output)
        writer.close()
        output.seek(0)

        return send_file(
            output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"EduKit_Page_{page}.pdf"
        )
    except Exception as e:
        return f"Could not split the PDF: {e}", 400


@app.route("/compress-pdf", methods=["POST"])
def compress_pdf():
    file = request.files.get("pdf")

    if not file or not file.filename.lower().endswith(".pdf"):
        return "Please select a PDF file.", 400

    try:
        reader = PdfReader(file)
        writer = PdfWriter()

        for page in reader.pages:
            try:
                page.compress_content_streams()
            except Exception:
                pass
            writer.add_page(page)

        output = BytesIO()
        writer.write(output)
        writer.close()
        output.seek(0)

        return send_file(
            output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="EduKit_Compressed.pdf"
        )
    except Exception as e:
        return f"Could not compress the PDF: {e}", 400


@app.route("/images-to-pdf", methods=["POST"])
def images_to_pdf():
    files = request.files.getlist("images")

    if not files:
        return "Please select at least one image.", 400

    try:
        from PIL import Image

        images = []
        for file in files:
            if not file.filename:
                continue
            image = Image.open(file.stream).convert("RGB")
            images.append(image)

        if not images:
            return "No valid images were selected.", 400

        output = BytesIO()
        first, rest = images[0], images[1:]
        first.save(output, format="PDF", save_all=True, append_images=rest)
        output.seek(0)

        return send_file(
            output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="EduKit_Images.pdf"
        )
    except Exception as e:
        return f"Could not create PDF from images: {e}", 400


@app.route("/pdf-to-images", methods=["POST"])
def pdf_to_images():
    file = request.files.get("pdf")

    if not file or not file.filename.lower().endswith(".pdf"):
        return "Please select a PDF file.", 400

    try:
        import fitz
        import zipfile

        pdf_bytes = file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for number, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                archive.writestr(
                    f"page_{number}.png",
                    pix.tobytes("png")
                )

        doc.close()
        zip_buffer.seek(0)

        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name="EduKit_PDF_Images.zip"
        )
    except Exception as e:
        return f"Could not convert PDF to images: {e}", 400

@app.route("/image-tools")
def image_tools():
    return render_template("image.html")
  
@app.route("/compress-image", methods=["POST"])
def compress_image():
    file = request.files.get("file")
    if not file:
        return "Please select an image.", 400
    try:
        img = Image.open(file.stream)
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, "white")
            bg.paste(img, mask=img.getchannel("A"))
            img = bg
        else:
            img = img.convert("RGB")
        output = BytesIO()
        img.save(output, "JPEG", quality=60, optimize=True)
        output.seek(0)
        return send_file(output, mimetype="image/jpeg", as_attachment=True,
                         download_name="EduKit_Compressed.jpg")
    except Exception as e:
        return f"Could not compress image: {e}", 400


@app.route("/resize-image", methods=["POST"])
def resize_image():
    file = request.files.get("file")
    width = request.form.get("width", type=int)
    height = request.form.get("height", type=int)
    if not file or not width or not height or width < 1 or height < 1:
        return "Please select an image and enter valid width and height.", 400
    try:
        img = Image.open(file.stream)
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        if img.mode == "RGBA":
            img = img.convert("RGB")
        output = BytesIO()
        img.save(output, "JPEG", quality=90)
        output.seek(0)
        return send_file(output, mimetype="image/jpeg", as_attachment=True,
                         download_name="EduKit_Resized.jpg")
    except Exception as e:
        return f"Could not resize image: {e}", 400


@app.route("/convert-image", methods=["POST"])
def convert_image():
    file = request.files.get("file")
    target = request.form.get("format", "png").lower()
    if not file:
        return "Please select an image.", 400
    if target not in {"jpg", "png", "webp"}:
        return "Invalid image format.", 400
    try:
        img = Image.open(file.stream)
        if target == "jpg":
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, "white")
                bg.paste(img, mask=img.getchannel("A"))
                img = bg
            else:
                img = img.convert("RGB")
            fmt, mime, name = "JPEG", "image/jpeg", "EduKit_Converted.jpg"
        elif target == "png":
            fmt, mime, name = "PNG", "image/png", "EduKit_Converted.png"
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
        else:
            fmt, mime, name = "WEBP", "image/webp", "EduKit_Converted.webp"
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
        output = BytesIO()
        img.save(output, fmt)
        output.seek(0)
        return send_file(output, mimetype=mime, as_attachment=True,
                         download_name=name)
    except Exception as e:
        return f"Could not convert image: {e}", 400

    # ==================== SEO ====================

@app.route("/robots.txt")
def robots_txt():
    content = """User-agent: *
Allow: /

Disallow: /admin
Disallow: /admin/
Disallow: /logout
Disallow: /admin/logout

Sitemap: https://edukit-3q1k.onrender.com/sitemap.xml
"""
    return content, 200, {
        "Content-Type": "text/plain; charset=utf-8"
    }


@app.route("/sitemap.xml")
def sitemap_xml():
    urls = [
        "https://edukit-3q1k.onrender.com/",
        "https://edukit-3q1k.onrender.com/tools",
        "https://edukit-3q1k.onrender.com/cgpa",
        "https://edukit-3q1k.onrender.com/percentage",
        "https://edukit-3q1k.onrender.com/attendance",
        "https://edukit-3q1k.onrender.com/qr",
        "https://edukit-3q1k.onrender.com/pdf",
        "https://edukit-3q1k.onrender.com/image-tools"
    ]

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for url in urls:
        xml += f"    <url><loc>{url}</loc></url>\n"

    xml += "</urlset>"

    return Response(
        xml,
        status=200,
        mimetype="application/xml"
    )

    xml_urls = "\n".join(
        f"    <url><loc>https://edukit-3q1k.onrender.com{url}</loc></url>"
        for url in urls
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{xml_urls}
</urlset>"""

    return xml, 200, {
        "Content-Type": "application/xml; charset=utf-8"
    }


if __name__ == "__main__":
    app.run(debug=True)
