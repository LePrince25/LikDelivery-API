def _post_init_seed_demo(env):
    """Exact port of main/seed.py (idempotent).

    7 accounts, 5 categories, 6 products, opening hours, shop/fleet links,
    client preferred société, default 80% cancellation rule.
    """
    if env["likdelivery.user"].sudo().search_count([]):
        return

    Category = env["likdelivery.product.category"].sudo()
    User = env["likdelivery.user"].sudo()
    Hour = env["likdelivery.opening.hour"].sudo()
    Product = env["likdelivery.product"].sudo()
    ShopDriver = env["likdelivery.shop.driver"].sudo()
    FleetDriver = env["likdelivery.fleet.driver"].sudo()
    Rule = env["likdelivery.cancellation.rule"].sudo()

    cats = {}
    for name, icon in [
        ("Restauration", "🍔"),
        ("Electronique", "📱"),
        ("Cosmetiques", "💄"),
        ("Epicerie", "🥖"),
        ("Pharmacie", "💊"),
    ]:
        cats[name] = Category.create({"name": name, "icon": icon})

    def make_user(phone, password, role, first, last, company=None,
                  lat=None, lon=None, address=None, validated=True,
                  vehicle=None, plate=None):
        user = User.create({
            "name": f"{first} {last}".strip() or phone,
            "phone": phone,
            "lik_role": role,
            "lik_first_name": first,
            "lik_last_name": last,
            "lik_company_name": company,
            "partner_latitude": lat,
            "partner_longitude": lon,
            "street": address,
            "lik_validated_by_admin": validated,
            "lik_vehicle_type": vehicle,
            "lik_license_plate": plate,
            "lik_average_rating": 5.0,
        })
        user.set_password(password)
        return user

    make_user("+22800000001", "admin123", "admin", "Admin", "System")
    fou = make_user("+22800000002", "fou123", "fournisseur", "Akpah", "Market",
                    "Super Market", 6.1725, 1.2253, "Agoe, Lome")
    liv = make_user("+22800000003", "liv123", "livreur", "Koffi", "Livreur",
                    None, 6.18, 1.23, "Lome", True, "Moto", "TG-1234-AB")
    cli = make_user("+22800000004", "cli123", "client", "Ama", "Client",
                    None, 6.16, 1.21, "Adidogome, Lome")
    soc = make_user("+22800000006", "soc123", "societe", "Express", "Fleet",
                    "Express Fleet TG", 6.17, 1.22, "Lome Centre")
    liv2 = make_user("+22800000007", "liv2123", "livreur", "Mensah", "Course",
                     None, 6.19, 1.22, "Lome", True, "Moto", "TG-5678-CD")

    for user in (fou, liv):
        for day in range(7):
            Hour.create({
                "partner_id": user.partner_id.id,
                "day_of_week": str(day),
                "open_time": 6.0,
                "close_time": 23.0,
            })

    ShopDriver.create({
        "supplier_id": fou.partner_id.id,
        "livreur_id": liv.partner_id.id,
        "is_active": True,
    })

    liv2.partner_id.lik_employer_societe_id = soc.partner_id
    FleetDriver.create({
        "societe_id": soc.partner_id.id,
        "livreur_id": liv2.partner_id.id,
        "origin": "internal",
        "is_active": True,
    })
    FleetDriver.create({
        "societe_id": soc.partner_id.id,
        "livreur_id": liv.partner_id.id,
        "origin": "external",
        "is_active": True,
    })

    cli.partner_id.lik_preferred_societe_id = soc.partner_id

    for cat_name, name, desc, price, stock, fragile, img in [
        ("Restauration", "Poulet pane", "Poulet pane accompagne", 3500, 20, False,
         "https://images.unsplash.com/photo-1604908176997-125f25cc6f3d?w=400"),
        ("Restauration", "Jus nature", "Jus de fruits frais", 1500, 50, False,
         "https://images.unsplash.com/photo-1613478223719-2ab802602423?w=400"),
        ("Epicerie", "Riz 5kg", "Riz blanc 5kg", 6500, 15, False,
         "https://images.unsplash.com/photo-1586201375761-83865001e31c?w=400"),
        ("Cosmetiques", "Savon artisanal", "Savon naturel", 1200, 30, True,
         "https://images.unsplash.com/photo-1600857544200-b2f666a9a2ec?w=400"),
    ]:
        Product.create({
            "supplier_id": fou.partner_id.id,
            "category_id": cats[cat_name].id,
            "name": name,
            "description": desc,
            "price": price,
            "stock": stock,
            "fragile": fragile,
            "lik_image_url": img,
            "active": True,
        })

    Rule.create({
        "min_hours": 0,
        "penalty_percent": 80.0,
        "applies_to_paid": True,
        "applies_to_cash": True,
        "active": True,
    })

    fou2 = make_user("+22800000005", "afi123", "fournisseur", "Afi", "Boutique",
                     "Boutique Afi", 6.15, 1.24, "Assigame, Lome")
    for day in range(7):
        Hour.create({
            "partner_id": fou2.partner_id.id,
            "day_of_week": str(day),
            "open_time": 7.0,
            "close_time": 22.0,
        })
    Product.create({
        "supplier_id": fou2.partner_id.id,
        "category_id": cats["Electronique"].id,
        "name": "Cable USB-C",
        "description": "Cable 1m",
        "price": 2500,
        "stock": 40,
        "active": True,
    })
    Product.create({
        "supplier_id": fou2.partner_id.id,
        "category_id": cats["Pharmacie"].id,
        "name": "Paracetamol",
        "description": "Boite de 10",
        "price": 1500,
        "stock": 100,
        "active": True,
    })

    # Back-office demo admin (res.users) — the platform admin account
    # (+22800000001) is API-only by design (D5); backend access uses this one.
    if not env["res.users"].search([("login", "=", "likadmin")]):
        env["res.users"].create({
            "name": "Lik Admin",
            "login": "likadmin",
            "password": "admin123",
            "lik_role_group_id": env.ref("likdelivery_core.group_lik_admin").id,
        })
