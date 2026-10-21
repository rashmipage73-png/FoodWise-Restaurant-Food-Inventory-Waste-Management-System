from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from pathlib import Path
from datetime import date, timedelta

app = Flask(__name__)
app.secret_key = "change-this-secret-key"
DB_PATH = Path(__file__).with_name("foodwise.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS ingredients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            quantity REAL NOT NULL DEFAULT 0,
            unit TEXT NOT NULL,
            min_stock REAL NOT NULL DEFAULT 0,
            price REAL NOT NULL DEFAULT 0,
            expiry_date TEXT,
            supplier TEXT
        );
        CREATE TABLE IF NOT EXISTS waste (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingredient_id INTEGER,
            ingredient_name TEXT NOT NULL,
            quantity REAL NOT NULL,
            reason TEXT NOT NULL,
            cost REAL NOT NULL,
            recorded_at TEXT NOT NULL,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact TEXT DEFAULT '',
            supplied_items TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingredient_id INTEGER,
            ingredient_name TEXT NOT NULL,
            quantity REAL NOT NULL,
            supplier TEXT DEFAULT '',
            estimated_cost REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'Pending',
            received_applied INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        );
        """)
        count = db.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
        if count == 0:
            today = date.today()
            sample = [
                ("Tomatoes", 22, "kg", 10, 40, (today + timedelta(days=2)).isoformat(), "Green Valley Farms"),
                ("Milk", 12, "L", 20, 55, (today + timedelta(days=1)).isoformat(), "Daily Dairy Co."),
                ("Spinach", 3, "kg", 5, 35, (today + timedelta(days=1)).isoformat(), "Green Valley Farms"),
                ("Paneer", 6, "kg", 5, 320, (today + timedelta(days=3)).isoformat(), "Daily Dairy Co."),
                ("Rice", 35, "kg", 15, 65, (today + timedelta(days=90)).isoformat(), "Harvest Wholesale"),
                ("Potatoes", 18, "kg", 10, 30, (today + timedelta(days=12)).isoformat(), "Green Valley Farms"),
                ("Onions", 24, "kg", 12, 32, (today + timedelta(days=14)).isoformat(), "Harvest Wholesale"),
            ]
            db.executemany("""INSERT INTO ingredients
                (name, quantity, unit, min_stock, price, expiry_date, supplier)
                VALUES (?, ?, ?, ?, ?, ?, ?)""", sample)
            db.execute("""INSERT INTO waste
                (ingredient_id, ingredient_name, quantity, reason, cost, recorded_at)
                VALUES (1, 'Tomatoes', 3, 'Spoilage', 120, ?)""", (today.isoformat(),))
            db.execute("""INSERT INTO waste
                (ingredient_id, ingredient_name, quantity, reason, cost, recorded_at)
                VALUES (2, 'Milk', 1, 'Over-purchasing', 55, ?)""", (today.isoformat(),))
        if db.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 0:
            db.executemany("INSERT INTO suppliers (name, contact, supplied_items) VALUES (?, ?, ?)", [
                ("Green Valley Farms", "98765 43210", "Tomatoes, Spinach, Potatoes"),
                ("Daily Dairy Co.", "98765 12340", "Milk, Paneer"),
                ("Harvest Wholesale", "98765 67890", "Rice, Onions"),
            ])

def money(value):
    return f"₹{value:,.2f}"

@app.context_processor
def utility_functions():
    return {"today": date.today().isoformat(), "money": money}

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    with get_db() as db:
        ingredients = db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
        waste_total = db.execute("SELECT COALESCE(SUM(cost), 0) FROM waste").fetchone()[0]
        waste_by_item = db.execute("""SELECT ingredient_name, SUM(cost) AS total
                                      FROM waste GROUP BY ingredient_name ORDER BY total DESC""").fetchall()
    today = date.today()
    low_stock = [i for i in ingredients if i["quantity"] <= i["min_stock"]]
    expiring = [i for i in ingredients if i["expiry_date"] and
                today <= date.fromisoformat(i["expiry_date"]) <= today + timedelta(days=3)]
    attention = {i["id"]: {"low": i["quantity"] <= i["min_stock"],
                           "days": (date.fromisoformat(i["expiry_date"]) - today).days
                           if i["expiry_date"] else None}
                 for i in ingredients}
    return render_template("dashboard.html", ingredients=ingredients, low_stock=low_stock,
                           expiring=expiring, waste_total=waste_total,
                           waste_by_item=waste_by_item, attention=attention)

@app.route("/inventory", methods=["GET", "POST"])
def inventory():
    with get_db() as db:
        if request.method == "POST":
            try:
                name = request.form["name"].strip()
                quantity = float(request.form["quantity"])
                unit = request.form["unit"].strip()
                min_stock = float(request.form["min_stock"])
                price = float(request.form["price"])
                expiry_date = request.form.get("expiry_date") or None
                supplier = request.form.get("supplier", "").strip()
                if not name or not unit or min(quantity, min_stock, price) < 0:
                    raise ValueError("Enter valid non-negative quantities and prices.")
                db.execute("""INSERT INTO ingredients
                    (name, quantity, unit, min_stock, price, expiry_date, supplier)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (name, quantity, unit, min_stock, price, expiry_date, supplier))
                flash(f"{name} added to inventory.", "success")
            except (ValueError, KeyError):
                flash("Please enter valid ingredient details. Quantity, minimum stock and price cannot be negative.", "error")
            return redirect(url_for("inventory"))
        items = db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
        suppliers = db.execute("SELECT name FROM suppliers ORDER BY name").fetchall()
    return render_template("inventory.html", items=items, suppliers=suppliers)

@app.route("/inventory/<int:item_id>/edit", methods=["POST"])
def edit_inventory(item_id):
    try:
        quantity = float(request.form["quantity"])
        min_stock = float(request.form["min_stock"])
        price = float(request.form["price"])
        if min(quantity, min_stock, price) < 0:
            raise ValueError
        with get_db() as db:
            db.execute("""UPDATE ingredients SET quantity=?, min_stock=?, price=?, expiry_date=?,
                          supplier=? WHERE id=?""",
                       (quantity, min_stock, price, request.form.get("expiry_date") or None,
                        request.form.get("supplier", "").strip(), item_id))
        flash("Ingredient updated.", "success")
    except (ValueError, KeyError):
        flash("Please enter valid non-negative values.", "error")
    return redirect(url_for("inventory"))

@app.route("/inventory/<int:item_id>/delete", methods=["POST"])
def delete_inventory(item_id):
    with get_db() as db:
        db.execute("DELETE FROM ingredients WHERE id=?", (item_id,))
    flash("Ingredient deleted.", "success")
    return redirect(url_for("inventory"))

@app.route("/waste", methods=["GET", "POST"])
def food_waste():
    with get_db() as db:
        if request.method == "POST":
            try:
                item_id = int(request.form["ingredient_id"])
                quantity = float(request.form["quantity"])
                reason = request.form["reason"]
                item = db.execute("SELECT * FROM ingredients WHERE id=?", (item_id,)).fetchone()
                if not item or quantity <= 0 or quantity > item["quantity"]:
                    raise ValueError
                cost = quantity * item["price"]
                db.execute("UPDATE ingredients SET quantity=quantity-? WHERE id=?", (quantity, item_id))
                db.execute("""INSERT INTO waste
                    (ingredient_id, ingredient_name, quantity, reason, cost, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (item_id, item["name"], quantity, reason, cost, date.today().isoformat()))
                flash("Food waste recorded and stock updated.", "success")
            except (ValueError, KeyError):
                flash("Choose an ingredient and a valid quantity not exceeding available stock.", "error")
            return redirect(url_for("food_waste"))
        items = db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
        waste = db.execute("SELECT * FROM waste ORDER BY id DESC").fetchall()
    return render_template("waste.html", items=items, waste=waste)

@app.route("/suppliers", methods=["GET", "POST"])
def suppliers():
    with get_db() as db:
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            contact = request.form.get("contact", "").strip()
            supplied_items = request.form.get("supplied_items", "").strip()
            if name:
                db.execute("INSERT INTO suppliers (name, contact, supplied_items) VALUES (?, ?, ?)",
                           (name, contact, supplied_items))
                flash("Supplier added.", "success")
            else:
                flash("Supplier name is required.", "error")
            return redirect(url_for("suppliers"))
        items = db.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
    return render_template("suppliers.html", items=items)

@app.route("/suppliers/<int:supplier_id>/delete", methods=["POST"])
def delete_supplier(supplier_id):
    with get_db() as db:
        db.execute("DELETE FROM suppliers WHERE id=?", (supplier_id,))
    flash("Supplier deleted.", "success")
    return redirect(url_for("suppliers"))

@app.route("/orders", methods=["GET", "POST"])
def orders():
    with get_db() as db:
        if request.method == "POST":
            try:
                item_id = int(request.form["ingredient_id"])
                quantity = float(request.form["quantity"])
                item = db.execute("SELECT * FROM ingredients WHERE id=?", (item_id,)).fetchone()
                if not item or quantity <= 0:
                    raise ValueError
                db.execute("""INSERT INTO purchase_orders
                    (ingredient_id, ingredient_name, quantity, supplier, estimated_cost, status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'Pending', ?)""",
                    (item_id, item["name"], quantity, item["supplier"], quantity * item["price"], date.today().isoformat()))
                flash("Purchase order created.", "success")
            except (ValueError, KeyError):
                flash("Select an ingredient and enter a quantity greater than zero.", "error")
            return redirect(url_for("orders"))
        items = db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
        all_orders = db.execute("SELECT * FROM purchase_orders ORDER BY id DESC").fetchall()
        recommendations = [i for i in items if i["quantity"] <= i["min_stock"]]
    return render_template("orders.html", items=items, orders=all_orders, recommendations=recommendations)

@app.route("/orders/<int:order_id>/receive", methods=["POST"])
def receive_order(order_id):
    with get_db() as db:
        order = db.execute("SELECT * FROM purchase_orders WHERE id=?", (order_id,)).fetchone()
        if order and not order["received_applied"]:
            if order["ingredient_id"]:
                db.execute("UPDATE ingredients SET quantity=quantity+? WHERE id=?",
                           (order["quantity"], order["ingredient_id"]))
            db.execute("UPDATE purchase_orders SET status='Received', received_applied=1 WHERE id=?", (order_id,))
            flash("Order received and stock updated once.", "success")
        elif order:
            flash("This order has already been received; stock was not changed again.", "error")
    return redirect(url_for("orders"))

@app.route("/orders/<int:order_id>/delete", methods=["POST"])
def delete_order(order_id):
    with get_db() as db:
        db.execute("DELETE FROM purchase_orders WHERE id=?", (order_id,))
    flash("Purchase order deleted.", "success")
    return redirect(url_for("orders"))

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
