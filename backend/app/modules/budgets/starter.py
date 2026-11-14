"""The budget built with Martin in the prototype, offered as a starting point for a new group."""

# (heading, [(post, [categories])]). Categories that don't exist yet are created for the group.
PROTOTYPE_BUDGET: list[tuple[str, list[tuple[str, list[str]]]]] = [
    ("Bolig", [("Husleje", ["Rent"]), ("Utilities", ["Utilities"])]),
    (
        "Faste udgifter",
        [
            ("Forsikring og medical", ["Insurance", "Medical"]),
            ("Phone og internet", ["Phone & internet"]),
            ("Abonnementer", ["Subscriptions"]),
        ],
    ),
    (
        "Variable udgifter",
        [
            ("Groceries og wine", ["Groceries", "Alcohol"]),
            ("Restaurants og take away", ["Restaurants & takeaway", "Cafe & coffee"]),
            ("Rejser og events", ["Travel expenses", "Attractions & events"]),
            ("Crosser", ["Crosser", "Fuel"]),
            ("Homeware", ["Homeware", "Home improvements"]),
            ("Bil og transport", ["Vehicle expenses", "Parking & tolls", "Taxis & ride shares"]),
            ("Personal care", ["Personal care"]),
            ("Pets", ["Pets"]),
            ("Skole (Compass)", ["Education"]),
            (
                "Tøj og shopping",
                ["Other shopping", "Clothing & accessories", "Gifts", "Media", "Electronics & technology", "Services"],
            ),
            ("Kontante hævninger, gebyrer og renter", ["Cash", "Fees", "Loans", "Government"]),
        ],
    ),
]
