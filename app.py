import os
import sqlite3
import uuid
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, abort
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

DATABASE = os.path.join(app.root_path, "food_orders.db")
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

# Initial food items: inserted into the database only once.
INITIAL_MENU = [
    ("Veg Burger", 90, "Delicious veg burger", "🍔"),
    ("Cheese Pizza", 180, "Cheesy pizza", "🍕"),
    ("Masala Dosa", 80, "Crispy masala dosa", "🥞"),
    ("Paneer Fried Rice", 140, "Tasty paneer fried rice", "🍚"),
    ("French Fries", 70, "Crispy french fries", "🍟"),
    ("Cold Coffee", 60, "Chilled cold coffee", "🥤")
]


def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


def initialize_database():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                address TEXT NOT NULL,
                items TEXT NOT NULL,
                total REAL NOT NULL,
                status TEXT DEFAULT 'Received',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS foods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                description TEXT DEFAULT '',
                emoji TEXT DEFAULT '🍽️',
                image TEXT DEFAULT ''
            )
        """)

        # Add the initial menu only if the food table is empty.
        count = db.execute(
            "SELECT COUNT(*) FROM foods"
        ).fetchone()[0]

        if count == 0:
            db.executemany("""
                INSERT INTO foods (name, price, description, emoji)
                VALUES (?, ?, ?, ?)
            """, INITIAL_MENU)


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def save_food_image(file):
    if not file or not file.filename:
        return None

    if not allowed_file(file.filename):
        return None

    extension = file.filename.rsplit(".", 1)[1].lower()
    filename = secure_filename(
        f"{uuid.uuid4().hex}.{extension}"
    )

    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename


def get_menu():
    with get_db() as db:
        return db.execute(
            "SELECT * FROM foods ORDER BY id"
        ).fetchall()


def get_cart_details():
    cart = session.get("cart", {})
    items = []
    total = 0

    menu = get_menu()

    for food in menu:
        quantity = int(cart.get(str(food["id"]), 0))

        if quantity > 0:
            subtotal = food["price"] * quantity

            items.append({
                **dict(food),
                "quantity": quantity,
                "subtotal": subtotal
            })

            total += subtotal

    return items, total


# Home page
@app.route("/")
def home():
    return render_template("index.html", menu=get_menu())


# Add food to cart
@app.route("/add-to-cart/<int:food_id>", methods=["POST"])
def add_to_cart(food_id):
    with get_db() as db:
        food = db.execute(
            "SELECT id FROM foods WHERE id = ?",
            (food_id,)
        ).fetchone()

    if not food:
        abort(404)

    cart = session.get("cart", {})
    key = str(food_id)
    cart[key] = int(cart.get(key, 0)) + 1
    session["cart"] = cart

    flash("Food added to cart!")
    return redirect(url_for("home"))


# Shopping cart
@app.route("/cart")
def cart():
    items, total = get_cart_details()
    return render_template("cart.html", items=items, total=total)


# Update cart
@app.route("/update-cart", methods=["POST"])
def update_cart():
    cart = session.get("cart", {})

    for key in list(cart.keys()):
        try:
            quantity = int(request.form.get(key, 0))
        except (ValueError, TypeError):
            quantity = 0

        if quantity <= 0:
            cart.pop(key, None)
        else:
            cart[key] = min(quantity, 20)

    session["cart"] = cart
    flash("Cart updated successfully!")
    return redirect(url_for("cart"))


# Checkout
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    items, total = get_cart_details()

    if not items:
        flash("Your cart is empty!")
        return redirect(url_for("home"))

    if request.method == "POST":
        name = request.form.get("customer_name", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()

        if not name or not phone or not address:
            flash("Please fill all details!")
            return render_template(
                "checkout.html", items=items, total=total
            )

        order_items = "; ".join(
            f'{item["name"]} x {item["quantity"]}'
            for item in items
        )

        with get_db() as db:
            cursor = db.execute("""
                INSERT INTO orders
                (customer_name, phone, address, items, total)
                VALUES (?, ?, ?, ?, ?)
            """, (name, phone, address, order_items, total))

            order_id = cursor.lastrowid

        session["cart"] = {}

        return render_template(
            "success.html",
            order_id=order_id,
            total=total
        )

    return render_template(
        "checkout.html", items=items, total=total
    )


# Admin login protection
def admin_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return function(*args, **kwargs)
    return wrapper


# Admin login
@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        admin_password = os.environ.get(
            "ADMIN_PASSWORD", "admin123"
        )

        if password == admin_password:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_orders"))

        flash("Incorrect password!")

    return render_template("admin_login.html")


# Admin orders dashboard
@app.route("/admin/orders")
@admin_required
def admin_orders():
    with get_db() as db:
        orders = db.execute(
            "SELECT * FROM orders ORDER BY id DESC"
        ).fetchall()

    return render_template("admin_orders.html", orders=orders)


# Admin food management page
@app.route("/admin/foods")
@admin_required
def admin_foods():
    return render_template("admin_food.html", foods=get_menu())


# Add food
@app.route("/admin/add-food", methods=["POST"])
@admin_required
def add_food():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    price_text = request.form.get("price", "").strip()
    emoji = request.form.get("emoji", "🍽️").strip() or "🍽️"
    image_file = request.files.get("image")

    if not name or not price_text:
        flash("Food name and price are required!")
        return redirect(url_for("admin_foods"))

    try:
        price = float(price_text)
        if price < 0:
            raise ValueError
    except ValueError:
        flash("Enter a valid price!")
        return redirect(url_for("admin_foods"))

    image_name = ""
    if image_file and image_file.filename:
        image_name = save_food_image(image_file)
        if not image_name:
            flash("Use JPG, JPEG, PNG or WEBP images only!")
            return redirect(url_for("admin_foods"))

    with get_db() as db:
        db.execute("""
            INSERT INTO foods (name, price, description, emoji, image)
            VALUES (?, ?, ?, ?, ?)
        """, (name, price, description, emoji, image_name))

    flash("Food added successfully!")
    return redirect(url_for("admin_foods"))


# Edit food
@app.route("/admin/edit-food/<int:food_id>", methods=["POST"])
@admin_required
def edit_food(food_id):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    price_text = request.form.get("price", "").strip()
    emoji = request.form.get("emoji", "🍽️").strip() or "🍽️"
    image_file = request.files.get("image")

    if not name or not price_text:
        flash("Food name and price are required!")
        return redirect(url_for("admin_foods"))

    try:
        price = float(price_text)
        if price < 0:
            raise ValueError
    except ValueError:
        flash("Enter a valid price!")
        return redirect(url_for("admin_foods"))

    with get_db() as db:
        food = db.execute(
            "SELECT * FROM foods WHERE id = ?", (food_id,)
        ).fetchone()

        if not food:
            abort(404)

        image_name = food["image"] or ""

        if image_file and image_file.filename:
            new_image = save_food_image(image_file)

            if not new_image:
                flash("Use JPG, JPEG, PNG or WEBP images only!")
                return redirect(url_for("admin_foods"))

            image_name = new_image

        db.execute("""
            UPDATE foods
            SET name = ?, price = ?, description = ?,
                emoji = ?, image = ?
            WHERE id = ?
        """, (name, price, description, emoji, image_name, food_id))

    flash("Food updated successfully!")
    return redirect(url_for("admin_foods"))


# Delete food
@app.route("/admin/delete-food/<int:food_id>", methods=["POST"])
@admin_required
def delete_food(food_id):
    with get_db() as db:
        food = db.execute(
            "SELECT * FROM foods WHERE id = ?", (food_id,)
        ).fetchone()

        if not food:
            abort(404)

        image_name = food["image"]

        db.execute(
            "DELETE FROM foods WHERE id = ?", (food_id,)
        )

    if image_name:
        image_path = os.path.join(
            app.config["UPLOAD_FOLDER"], image_name
        )
        if os.path.isfile(image_path):
            os.remove(image_path)

    cart = session.get("cart", {})
    cart.pop(str(food_id), None)
    session["cart"] = cart

    flash("Food deleted successfully!")
    return redirect(url_for("admin_foods"))


# Update order status
@app.route("/admin/update-status/<int:order_id>", methods=["POST"])
@admin_required
def update_status(order_id):
    status = request.form.get("status", "")

    allowed_statuses = {
        "Received", "Preparing",
        "Out for delivery", "Completed"
    }

    if status not in allowed_statuses:
        abort(400)

    with get_db() as db:
        db.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (status, order_id)
        )

    flash("Order status updated!")
    return redirect(url_for("admin_orders"))


# Admin logout
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("home"))


if __name__ == "__main__":
    initialize_database()
    app.run(debug=True)