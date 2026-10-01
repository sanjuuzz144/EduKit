from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
from PIL import Image
from io import BytesIO

image_bp = Blueprint("image_tools", __name__, url_prefix="/image")

ALLOWED = {"jpg", "jpeg", "png", "webp"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED

@image_bp.route("/")
def image_home():
    return render_template("image.html")

@image_bp.route("/compress", methods=["POST"])
def compress_image():
    file = request.files.get("file")
    if not file or not allowed_file(file.filename):
        flash("Choose a JPG, PNG or WEBP image.")
        return redirect(url_for("image_tools.image_home"))

    try:
        img = Image.open(file.stream)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

        output = BytesIO()

        if img.format == "PNG":
            img.save(output, "PNG", optimize=True)
            ext = "png"
            mimetype = "image/png"
        else:
            if img.mode == "RGBA":
                # JPEG does not support transparency.
                background = Image.new("RGB", img.size, "white")
                background.paste(img, mask=img.getchannel("A"))
                img = background
            else:
                img = img.convert("RGB")
            img.save(output, "JPEG", quality=70, optimize=True)
            ext = "jpg"
            mimetype = "image/jpeg"

        output.seek(0)
        return send_file(output, mimetype=mimetype, as_attachment=True,
                         download_name=f"EduKit_compressed.{ext}")
    except Exception as e:
        return f"Could not compress image: {e}", 400

@image_bp.route("/resize", methods=["POST"])
def resize_image():
    file = request.files.get("file")
    width = request.form.get("width", type=int)
    height = request.form.get("height", type=int)

    if not file or not allowed_file(file.filename):
        flash("Choose a JPG, PNG or WEBP image.")
        return redirect(url_for("image_tools.image_home"))

    if not width or width < 1 or not height or height < 1:
        flash("Enter a valid width and height.")
        return redirect(url_for("image_tools.image_home"))

    try:
        img = Image.open(file.stream)
        img = img.resize((width, height), Image.Resampling.LANCZOS)

        output = BytesIO()
        original = file.filename.rsplit(".", 1)[-1].lower()

        if original in ("jpg", "jpeg"):
            if img.mode == "RGBA":
                background = Image.new("RGB", img.size, "white")
                background.paste(img, mask=img.getchannel("A"))
                img = background
            img.save(output, "JPEG", quality=90, optimize=True)
            mimetype = "image/jpeg"
            ext = "jpg"
        elif original == "webp":
            img.save(output, "WEBP", quality=90, method=6)
            mimetype = "image/webp"
            ext = "webp"
        else:
            img.save(output, "PNG", optimize=True)
            mimetype = "image/png"
            ext = "png"

        output.seek(0)
        return send_file(output, mimetype=mimetype, as_attachment=True,
                         download_name=f"EduKit_resized.{ext}")
    except Exception as e:
        return f"Could not resize image: {e}", 400

@image_bp.route("/convert", methods=["POST"])
def convert_image():
    file = request.files.get("file")
    target = request.form.get("format", "").lower()

    if not file or not allowed_file(file.filename):
        flash("Choose a JPG, PNG or WEBP image.")
        return redirect(url_for("image_tools.image_home"))

    if target not in {"jpg", "png", "webp"}:
        flash("Choose a valid output format.")
        return redirect(url_for("image_tools.image_home"))

    try:
        img = Image.open(file.stream)

        if target == "jpg":
            if img.mode == "RGBA":
                background = Image.new("RGB", img.size, "white")
                background.paste(img, mask=img.getchannel("A"))
                img = background
            else:
                img = img.convert("RGB")
            fmt, mimetype = "JPEG", "image/jpeg"
        elif target == "png":
            fmt, mimetype = "PNG", "image/png"
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
        else:
            fmt, mimetype = "WEBP", "image/webp"
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")

        output = BytesIO()
        img.save(output, fmt, quality=90 if target == "webp" else None)
        output.seek(0)

        return send_file(output, mimetype=mimetype, as_attachment=True,
                         download_name=f"EduKit_converted.{target}")
    except Exception as e:
        return f"Could not convert image: {e}", 400
