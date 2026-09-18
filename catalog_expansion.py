"""Curated expansion for a Kenyan supermarket starter catalogue.

These are product identities/variants intended to make a fresh Denmart install
useful immediately. Prices and live availability remain admin-controlled.
"""


def _add(catalog, category, entries):
    seen = {name.lower() for name, _, _ in catalog.get(category, [])}
    for name, brand, unit in entries:
        if name.lower() not in seen:
            catalog.setdefault(category, []).append((name, brand, unit))
            seen.add(name.lower())


def _variants(catalog, category, families):
    """families = [(brand, base, [sizes], unit)]"""
    entries = []
    for brand, base, sizes, unit in families:
        for size in sizes:
            entries.append((f"{brand} {base} {size}".strip(), brand, unit))
    _add(catalog, category, entries)


def expand_catalog(catalog):
    _variants(catalog, "Bakery & Bread", [
        ("Superloaf", "White Bread", ["400g", "600g", "800g"], "loaf"),
        ("Superloaf", "Brown Bread", ["400g", "600g", "800g"], "loaf"),
        ("Broadways", "White Bread", ["400g", "600g", "800g"], "loaf"),
        ("Broadways", "Brown Bread", ["400g", "600g", "800g"], "loaf"),
        ("Supa Loaf", "White Bread", ["400g", "600g", "800g"], "loaf"),
        ("Supa Loaf", "Brown Bread", ["400g", "600g", "800g"], "loaf"),
        ("Eros", "White Bread", ["400g", "600g", "800g"], "loaf"),
        ("Eros", "Brown Bread", ["400g", "600g", "800g"], "loaf"),
        ("Fresh Queen", "White Bread", ["400g", "600g", "800g"], "loaf"),
        ("Fresh Queen", "Brown Bread", ["400g", "600g", "800g"], "loaf"),
        ("Naivas", "White Bread", ["400g", "600g", "800g"], "loaf"),
        ("Naivas", "Brown Bread", ["400g", "600g", "800g"], "loaf"),
        ("Naivas", "Milk Buns", ["4s", "6s", "8s"], "pack"),
        ("Fresh Queen", "Vanilla Cookies", ["200g", "400g", "800g"], "pack"),
        ("Fresh Queen", "Tea Scones", ["4s", "6s", "12s"], "pack"),
    ])

    _variants(catalog, "Dairy, Eggs & Chilled", [
        ("Brookside", "Fresh Milk", ["250ml", "500ml", "1L", "2L"], "pack"),
        ("KCC", "Fresh Milk", ["250ml", "500ml", "1L", "2L"], "pack"),
        ("Daima", "Fresh Milk", ["250ml", "500ml", "1L", "2L"], "pack"),
        ("Fresha", "Fresh Milk", ["250ml", "500ml", "1L", "2L"], "pack"),
        ("Ilara", "Fresh Milk", ["250ml", "500ml", "1L", "2L"], "pack"),
        ("Tuzo", "Fresh Milk", ["250ml", "500ml", "1L", "2L"], "pack"),
        ("Mount Kenya", "Premium Fino Milk", ["500ml", "1L", "2L"], "pack"),
        ("Brookside", "Long Life Milk", ["200ml", "500ml", "1L"], "pack"),
        ("Daima", "UHT Milk Fino", ["200ml", "500ml", "1L"], "pack"),
        ("Brookside", "Yoghurt Strawberry", ["150ml", "250ml", "500ml"], "pack"),
        ("Brookside", "Yoghurt Vanilla", ["150ml", "250ml", "500ml"], "pack"),
        ("Delamere", "Strawberry Yoghurt", ["150ml", "250ml", "500ml"], "pack"),
        ("Fresha", "Strawberry Yoghurt", ["150ml", "250ml", "500ml"], "pack"),
        ("Happy Cow", "Cheddar Cheese", ["200g", "400g", "800g"], "pack"),
        ("Brookside", "Butter Salted", ["250g", "500g", "1kg"], "pack"),
        ("Brookside", "Butter Unsalted", ["250g", "500g", "1kg"], "pack"),
        ("Fresh Fri", "Margarine", ["250g", "500g", "1kg"], "tub"),
        ("Blue Band", "Margarine", ["250g", "500g", "1kg"], "tub"),
    ])

    _variants(catalog, "Breakfast & Cereals", [
        ("Weetabix", "Original", ["215g", "430g", "950g"], "box"),
        ("Kellogg's", "Corn Flakes", ["250g", "500g", "1kg"], "box"),
        ("Nestle", "Milo", ["200g", "400g", "900g"], "tin"),
        ("Nestle", "Nesquik", ["200g", "400g", "700g"], "tin"),
        ("NutriDay", "Corn Flakes", ["250g", "500g", "1kg"], "box"),
        ("Kellogg's", "Frosties", ["250g", "500g", "750g"], "box"),
        ("Kellogg's", "Rice Krispies", ["200g", "400g", "700g"], "box"),
        ("Kellogg's", "Special K", ["300g", "500g", "750g"], "box"),
        ("Quaker", "Oats", ["500g", "1kg", "2kg"], "pack"),
        ("Unga", "Porridge Oats", ["500g", "1kg", "2kg"], "pack"),
        ("BIDCO", "Porridge Mix", ["500g", "1kg", "2kg"], "pack"),
        ("Mum's", "Granola", ["250g", "500g", "1kg"], "pack"),
        ("Naivas", "Corn Flakes", ["250g", "500g", "1kg"], "box"),
        ("Naivas", "Muesli", ["500g", "1kg", "2kg"], "pack"),
    ])

    _variants(catalog, "Rice, Flour, Pasta & Grains", [
        ("Pembe", "Maize Meal", ["1kg", "2kg", "5kg"], "bag"),
        ("Jogoo", "Maize Meal", ["1kg", "2kg", "5kg"], "bag"),
        ("Hostess", "Maize Meal", ["1kg", "2kg", "5kg"], "bag"),
        ("Tupike", "Maize Meal", ["1kg", "2kg", "5kg"], "bag"),
        ("Soko", "Maize Meal", ["1kg", "2kg", "5kg"], "bag"),
        ("Exe", "Maize Meal", ["1kg", "2kg", "5kg"], "bag"),
        ("Amaize", "Maize Meal", ["1kg", "2kg", "5kg"], "bag"),
        ("Pearl", "Pishori Rice", ["1kg", "2kg", "5kg"], "bag"),
        ("Sunrice", "Basmati Rice", ["1kg", "2kg", "5kg"], "bag"),
        ("Daawat", "Basmati Rice", ["1kg", "2kg", "5kg"], "bag"),
        ("Mwea", "Pishori Rice", ["1kg", "2kg", "5kg"], "bag"),
        ("Ndovu", "Rice", ["1kg", "2kg", "5kg"], "bag"),
        ("Pembe", "All Purpose Flour", ["1kg", "2kg", "5kg"], "bag"),
        ("Exe", "All Purpose Flour", ["1kg", "2kg", "5kg"], "bag"),
        ("Hostess", "All Purpose Flour", ["1kg", "2kg", "5kg"], "bag"),
        ("Ajab", "All Purpose Flour", ["1kg", "2kg", "5kg"], "bag"),
        ("Jogoo", "Atta Flour", ["1kg", "2kg", "5kg"], "bag"),
        ("Unga", "Chapati Flour", ["1kg", "2kg", "5kg"], "bag"),
        ("Unga", "Self Raising Flour", ["1kg", "2kg", "5kg"], "bag"),
        ("Blue Band", "Baking Flour", ["500g", "1kg", "2kg"], "bag"),
        ("Pasta Italia", "Spaghetti", ["250g", "500g", "1kg"], "pack"),
        ("Santa Lucia", "Spaghetti", ["250g", "500g", "1kg"], "pack"),
        ("Pasta Italia", "Macaroni", ["250g", "500g", "1kg"], "pack"),
        ("Pasta Italia", "Penne", ["250g", "500g", "1kg"], "pack"),
    ])

    _variants(catalog, "Sugar, Tea & Coffee", [
        ("Mumias", "Sugar", ["1kg", "2kg", "5kg"], "bag"),
        ("Kabras", "Sugar", ["1kg", "2kg", "5kg"], "bag"),
        ("Kabras", "Brown Sugar", ["500g", "1kg", "2kg"], "bag"),
        ("Mumias", "Icing Sugar", ["500g", "1kg", "2kg"], "bag"),
        ("Ketepa", "Tea Bags", ["25s", "50s", "100s"], "pack"),
        ("Kericho Gold", "Tea Bags", ["25s", "50s", "100s"], "pack"),
        ("Kericho Gold", "Loose Leaf Tea", ["100g", "250g", "500g"], "pack"),
        ("Fresh Fri", "Tea Bags", ["25s", "50s", "100s"], "pack"),
        ("Lyons", "Tea Bags", ["25s", "50s", "100s"], "pack"),
        ("Dormans", "Ground Coffee", ["100g", "250g", "500g"], "pack"),
        ("Java", "East African Blend Ground Coffee", ["100g", "250g", "500g"], "pack"),
        ("MacCoffee", "Instant Coffee", ["50g", "100g", "200g"], "jar"),
        ("Nescafe", "Classic Instant Coffee", ["50g", "100g", "200g"], "jar"),
        ("Blue Band", "Hot Chocolate Drink", ["200g", "400g", "800g"], "pack"),
    ])

    _variants(catalog, "Cooking Oils, Sauces & Spices", [
        ("Elianto", "Cooking Oil", ["500ml", "1L", "2L", "3L", "5L"], "bottle"),
        ("Rina", "Cooking Oil", ["500ml", "1L", "2L", "3L", "5L"], "bottle"),
        ("Golden Fry", "Cooking Oil", ["1L", "2L", "3L", "5L"], "bottle"),
        ("Golden Drop", "Cooking Oil", ["1L", "2L", "3L", "5L"], "bottle"),
        ("Fresh Fri", "Cooking Oil", ["1L", "2L", "3L", "5L"], "bottle"),
        ("BIDCO", "Sunflower Oil", ["1L", "2L", "3L", "5L"], "bottle"),
        ("Soybean", "Cooking Oil", ["1L", "2L", "3L", "5L"], "bottle"),
        ("Peptang", "Tomato Sauce", ["300g", "500g", "1kg"], "bottle"),
        ("Heinz", "Tomato Ketchup", ["342g", "567g", "1kg"], "bottle"),
        ("Royco", "Mchuzi Mix", ["100g", "200g", "500g"], "pack"),
        ("Royco", "Chicken Cubes", ["10s", "20s", "40s"], "pack"),
        ("Royco", "Beef Cubes", ["10s", "20s", "40s"], "pack"),
        ("Tropical Heat", "Black Pepper", ["50g", "100g", "200g"], "jar"),
        ("Tropical Heat", "Pilau Masala", ["50g", "100g", "200g"], "jar"),
        ("Tropical Heat", "Curry Powder", ["50g", "100g", "200g"], "jar"),
        ("Tropical Heat", "Chilli Sauce", ["150ml", "300ml", "500ml"], "bottle"),
        ("Zesta", "Mango Chutney", ["225g", "450g", "900g"], "jar"),
        ("Zesta", "Peanut Butter", ["400g", "800g", "1kg"], "jar"),
        ("Blue Band", "Peanut Butter", ["400g", "800g", "1kg"], "jar"),
    ])

    _variants(catalog, "Food Cupboard", [
        ("Kensal", "Tomato Paste", ["200g", "400g", "800g"], "tin"),
        ("Kensal", "Baked Beans", ["210g", "420g", "820g"], "tin"),
        ("Heinz", "Baked Beans", ["200g", "415g", "800g"], "tin"),
        ("Kensal", "Sweet Corn", ["340g", "425g", "850g"], "tin"),
        ("Princes", "Tuna", ["95g", "185g", "400g"], "tin"),
        ("Kensal", "Mixed Vegetables", ["340g", "680g", "1.5kg"], "tin"),
        ("Del Monte", "Tomato Sauce", ["300g", "500g", "1kg"], "bottle"),
        ("Del Monte", "Fruit Cocktail", ["420g", "825g", "2.6kg"], "tin"),
        ("Del Monte", "Pineapple Slices", ["234g", "432g", "820g"], "tin"),
        ("Nescafe", "Hot Cocoa", ["200g", "400g", "800g"], "jar"),
        ("Knorr", "Soup Mix", ["50g", "100g", "200g"], "pack"),
        ("Royco", "Cream of Mushroom Soup", ["45g", "90g", "180g"], "pack"),
        ("Aryuva", "Coconut Cream", ["65ml", "200ml", "400ml"], "pack"),
        ("Santa Maria", "Taco Seasoning", ["20g", "50g", "100g"], "pack"),
        ("Nutrameal", "Yellow Beans", ["500g", "1kg", "2kg"], "pack"),
        ("Nutrameal", "Ndengu", ["500g", "1kg", "2kg"], "pack"),
        ("Nutrameal", "Njahi Beans", ["500g", "1kg", "2kg"], "pack"),
        ("Naivas", "White Beans", ["500g", "1kg", "2kg"], "pack"),
    ])

    _variants(catalog, "Snacks, Biscuits & Confectionery", [
        ("Manji", "Family Biscuits", ["200g", "400g", "800g"], "pack"),
        ("Manji", "Digestive Biscuits", ["200g", "400g", "800g"], "pack"),
        ("Manji", "Lemon Cream Biscuits", ["150g", "300g", "600g"], "pack"),
        ("Mcvitie's", "Digestive Biscuits", ["250g", "400g", "800g"], "pack"),
        ("Oreo", "Original", ["133g", "154g", "300g"], "pack"),
        ("Parle", "Parle-G Original Glucose Biscuits", ["150g", "382.5g", "765g"], "pack"),
        ("Parle", "Hide & Seek Black Bourbon", ["100g", "200g", "400g"], "pack"),
        ("Cadbury", "Dairy Milk", ["40g", "45g", "80g", "180g"], "bar"),
        ("Cadbury", "Top Deck", ["40g", "80g", "160g"], "bar"),
        ("Nestle", "KitKat", ["17g", "41.5g", "4 Finger"], "bar"),
        ("Mars", "Chocolate Bar", ["51g", "70g", "90g"], "bar"),
        ("Snickers", "Chocolate Bar", ["50g", "80g", "200g"], "bar"),
        ("Tropical Heat", "Potato Crisps", ["50g", "100g", "200g"], "pack"),
        ("Tropical Heat", "Chilli Lemon Crisps", ["50g", "100g", "200g"], "pack"),
        ("Pringles", "Original", ["70g", "165g", "200g"], "can"),
        ("Pringles", "Sour Cream & Onion", ["70g", "165g", "200g"], "can"),
        ("Chupa Chups", "Lollipops", ["5s", "10s", "20s"], "pack"),
        ("Mayfair", "Cake Slices", ["2s", "4s", "8s"], "pack"),
    ])

    _variants(catalog, "Drinks & Water", [
        ("Coca-Cola", "Soft Drink", ["300ml", "500ml", "1.25L", "2L"], "bottle"),
        ("Fanta", "Orange", ["300ml", "500ml", "1.25L", "2L"], "bottle"),
        ("Sprite", "Lemon Lime", ["300ml", "500ml", "1.25L", "2L"], "bottle"),
        ("7 Up", "Soft Drink", ["300ml", "500ml", "1.25L", "2L"], "bottle"),
        ("Minute Maid", "Orange Pulpy Juice", ["400ml", "1L", "2L"], "bottle"),
        ("Del Monte", "Mango Juice", ["1L", "2L", "3L"], "pack"),
        ("Del Monte", "Orange Juice", ["1L", "2L", "3L"], "pack"),
        ("Kevian Afia", "Mango Juice", ["300ml", "500ml", "1L"], "bottle"),
        ("Quencher", "Orange Drink", ["300ml", "500ml", "1L"], "bottle"),
        ("Sawa", "Water", ["500ml", "1L", "1.5L", "5L"], "bottle"),
        ("Keringet", "Mineral Water", ["500ml", "1L", "1.5L", "5L"], "bottle"),
        ("Aquamist", "Mineral Water", ["500ml", "1L", "1.5L", "5L"], "bottle"),
        ("Dasani", "Water", ["500ml", "1L", "1.5L", "5L"], "bottle"),
        ("Pepsi", "Soft Drink", ["300ml", "500ml", "1.25L", "2L"], "bottle"),
        ("Red Bull", "Energy Drink", ["250ml", "355ml", "473ml"], "can"),
        ("Monster", "Energy Drink", ["355ml", "500ml", "1L"], "can"),
        ("Stoney", "Ginger Beer", ["300ml", "500ml", "1.25L"], "bottle"),
        ("Power Play", "Energy Drink", ["300ml", "500ml", "1L"], "can"),
    ])

    _variants(catalog, "Baby & Kids", [
        ("Pampers", "Baby-Dry Diapers Size", ["2", "3", "4", "5", "6"], "pack"),
        ("Huggies", "Diapers Size", ["2", "3", "4", "5", "6"], "pack"),
        ("Molfix", "Diapers Size", ["3", "4", "5", "6"], "pack"),
        ("Softcare", "Diapers Size", ["3", "4", "5", "6"], "pack"),
        ("Nipnap", "Baby Wipes", ["72s", "80s", "120s"], "pack"),
        ("Huggies", "Baby Wipes", ["56s", "64s", "80s"], "pack"),
        ("Johnson's", "Baby Lotion", ["100ml", "200ml", "400ml"], "bottle"),
        ("Johnson's", "Baby Shampoo", ["100ml", "200ml", "400ml"], "bottle"),
        ("J&J", "Baby Powder", ["100g", "200g", "400g"], "bottle"),
        ("Nestle", "Nan Infant Formula", ["400g", "800g", "1.8kg"], "tin"),
        ("Nestle", "Cerelac Infant Cereal", ["200g", "400g", "800g"], "box"),
        ("Aptamil", "Infant Formula", ["400g", "800g", "1.2kg"], "tin"),
        ("Cool Baby", "Baby Pants", ["Small", "Medium", "Large", "XL"], "pack"),
        ("Mom Easy", "Baby Bottle", ["125ml", "250ml", "330ml"], "piece"),
    ])

    _variants(catalog, "Beauty & Personal Care", [
        ("Colgate", "Maximum Cavity Protection", ["35ml", "70ml", "100ml", "140ml"], "tube"),
        ("Colgate", "Herbal With Salt", ["70g", "140g"], "tube"),
        ("Colgate", "Charcoal Gentle", ["35g", "70g", "140g"], "tube"),
        ("Closeup", "Red Hot", ["50ml", "100ml", "150ml"], "tube"),
        ("Pepsodent", "Herbal", ["50ml", "100ml", "150ml"], "tube"),
        ("Oral-B", "Toothbrush", ["1pc", "2pc", "4pc"], "piece"),
        ("Listerine", "Mouthwash", ["250ml", "500ml", "1L"], "bottle"),
        ("Nivea", "Men Creme", ["75ml", "150ml", "250ml"], "tin"),
        ("Nivea", "Body Lotion", ["250ml", "400ml", "625ml"], "bottle"),
        ("Vaseline", "Petroleum Jelly", ["50ml", "100ml", "250ml"], "jar"),
        ("Vaseline", "Cocoa Radiant Lotion", ["200ml", "400ml", "625ml"], "bottle"),
        ("Dove", "Beauty Bar", ["90g", "2x90g", "4x90g"], "pack"),
        ("Dove", "Body Wash", ["250ml", "500ml", "750ml"], "bottle"),
        ("Nice & Lovely", "Body Lotion", ["250ml", "500ml", "1L"], "bottle"),
        ("Cussons", "Imperial Leather Soap", ["85g", "3x85g", "6x85g"], "pack"),
        ("J&J", "Cotton Buds", ["60s", "100s", "200s"], "pack"),
        ("Pantene", "Shampoo", ["180ml", "360ml", "650ml"], "bottle"),
        ("Head & Shoulders", "Shampoo", ["180ml", "360ml", "650ml"], "bottle"),
        ("Tresemme", "Shampoo", ["250ml", "400ml", "900ml"], "bottle"),
        ("Axe", "Deodorant Spray", ["100ml", "150ml", "250ml"], "can"),
        ("Rexona", "Roll On", ["40ml", "50ml", "100ml"], "roll-on"),
        ("Always", "Ultra Pads", ["8s", "16s", "32s"], "pack"),
        ("Molped", "UltraSoft Pads", ["8s", "16s", "32s"], "pack"),
        ("Gillette", "Blue II Razors", ["5s", "10s", "20s"], "pack"),
    ])

    _variants(catalog, "Laundry & Home Care", [
        ("Omo", "Detergent", ["500g", "1kg", "2kg", "3kg"], "pack"),
        ("Ariel", "Detergent", ["500g", "1kg", "2kg", "3kg"], "pack"),
        ("Sunlight", "Detergent", ["500g", "1kg", "2kg", "3kg"], "pack"),
        ("Persil", "Detergent", ["500g", "1kg", "2kg", "3kg"], "pack"),
        ("Rinz", "Detergent", ["500g", "1kg", "2kg", "3kg"], "pack"),
        ("Minimax", "Detergent", ["500g", "1kg", "2kg"], "pack"),
        ("Sta Soft", "Fabric Softener", ["500ml", "1L", "2L"], "bottle"),
        ("Ariel", "Fabric Softener", ["500ml", "1L", "2L"], "bottle"),
        ("Downy", "Fabric Softener", ["500ml", "1L", "2L"], "bottle"),
        ("Harpic", "Toilet Cleaner", ["500ml", "750ml", "1L"], "bottle"),
        ("Domestos", "Bleach", ["500ml", "750ml", "1L"], "bottle"),
        ("Jik", "Bleach", ["500ml", "1L", "2L"], "bottle"),
        ("Dettol", "Multipurpose Cleaner", ["500ml", "1L", "2L"], "bottle"),
        ("Glade", "Air Freshener", ["300ml", "400ml", "500ml"], "can"),
        ("Doom", "Insect Killer", ["150ml", "300ml", "600ml"], "can"),
        ("Mortein", "Insect Killer", ["150ml", "300ml", "600ml"], "can"),
        ("Jeyes", "Fluid", ["500ml", "1L", "2L"], "bottle"),
    ])

    _variants(catalog, "Household & Kitchen", [
        ("Various", "Aluminium Foil", ["10m", "20m", "50m"], "roll"),
        ("Various", "Cling Film", ["20m", "30m", "50m"], "roll"),
        ("Various", "Garbage Bags Small", ["20s", "30s", "50s"], "pack"),
        ("Various", "Garbage Bags Medium", ["20s", "30s", "50s"], "pack"),
        ("Various", "Garbage Bags Large", ["10s", "20s", "30s"], "pack"),
        ("Kenpoly", "Food Storage Containers", ["3pc", "5pc", "10pc"], "set"),
        ("Lock & Lock", "Food Storage Containers", ["2pc", "4pc", "6pc"], "set"),
        ("Luminarc", "Glass Tumbler Set", ["3pc", "6pc", "12pc"], "set"),
        ("Pyrex", "Glass Dish", ["500ml", "1L", "2L"], "piece"),
        ("Pasabahce", "Glass Tumbler", ["3pc", "6pc", "12pc"], "set"),
        ("Tramontina", "Kitchen Knife", ["1pc", "3pc", "6pc"], "piece"),
        ("Tefal", "Frying Pan", ["20cm", "24cm", "28cm"], "piece"),
        ("Tefal", "Cooking Pot", ["2L", "3L", "5L"], "piece"),
        ("Kenpoly", "Plastic Bucket", ["10L", "15L", "20L"], "piece"),
        ("Various", "Broom Hard", ["1pc", "2pc", "3pc"], "piece"),
        ("Various", "Mop Head", ["1pc", "2pc", "4pc"], "piece"),
        ("Various", "Scrubbing Brush", ["1pc", "2pc", "4pc"], "piece"),
        ("Various", "Dishwashing Sponge", ["3s", "6s", "12s"], "pack"),
        ("Various", "Clothes Hangers", ["5s", "10s", "20s"], "pack"),
        ("Various", "Laundry Basket", ["30L", "50L", "70L"], "piece"),
    ])

    _variants(catalog, "Fresh Produce", [
        ("Fresh Produce", "Potatoes", ["500g", "1kg", "2kg", "5kg"], "kg"),
        ("Fresh Produce", "Onions", ["500g", "1kg", "2kg", "5kg"], "kg"),
        ("Fresh Produce", "Red Onions", ["500g", "1kg", "2kg"], "kg"),
        ("Fresh Produce", "Tomatoes", ["500g", "1kg", "2kg"], "kg"),
        ("Fresh Produce", "Bananas", ["500g", "1kg", "2kg"], "kg"),
        ("Fresh Produce", "Avocado", ["2s", "4s", "6s"], "pack"),
        ("Fresh Produce", "Mangoes", ["2s", "4s", "6s"], "pack"),
        ("Fresh Produce", "Oranges", ["500g", "1kg", "2kg"], "kg"),
        ("Fresh Produce", "Apples", ["500g", "1kg", "2kg"], "kg"),
        ("Fresh Produce", "Paw Paw", ["1pc", "2pc", "3pc"], "piece"),
        ("Fresh Produce", "Watermelon", ["1pc", "2pc", "4pc"], "piece"),
        ("Fresh Produce", "Cabbage", ["1pc", "2pc", "4pc"], "piece"),
        ("Fresh Produce", "Spinach", ["250g", "500g", "1kg"], "pack"),
        ("Fresh Produce", "Sukuma Wiki", ["250g", "500g", "1kg"], "pack"),
        ("Fresh Produce", "Green Peppers", ["250g", "500g", "1kg"], "pack"),
        ("Fresh Produce", "Carrots", ["500g", "1kg", "2kg"], "kg"),
        ("Fresh Produce", "Cucumber", ["500g", "1kg", "2kg"], "kg"),
        ("Fresh Produce", "Lemons", ["250g", "500g", "1kg"], "kg"),
        ("Fresh Produce", "Ginger", ["100g", "250g", "500g"], "pack"),
        ("Fresh Produce", "Garlic", ["100g", "250g", "500g"], "pack"),
    ])

    _variants(catalog, "Meat, Poultry & Fish", [
        ("Kenchic", "Whole Chicken", ["1kg", "1.5kg", "2kg"], "kg"),
        ("Kenchic", "Chicken Breast", ["500g", "1kg", "2kg"], "pack"),
        ("Kenchic", "Chicken Wings", ["500g", "1kg", "2kg"], "pack"),
        ("Kenchic", "Chicken Drumsticks", ["500g", "1kg", "2kg"], "pack"),
        ("Farmers Choice", "Beef Sausages", ["250g", "500g", "1kg"], "pack"),
        ("Farmers Choice", "Smokies", ["250g", "500g", "1kg"], "pack"),
        ("Farmers Choice", "Bacon", ["200g", "400g", "800g"], "pack"),
        ("Farmers Choice", "Beef Burger Patties", ["200g", "400g", "800g"], "pack"),
        ("Fresh Meat", "Beef Mince", ["500g", "1kg", "2kg"], "pack"),
        ("Fresh Meat", "Beef Steak", ["500g", "1kg", "2kg"], "pack"),
        ("Fresh Meat", "Beef Rump", ["500g", "1kg", "2kg"], "pack"),
        ("Fresh Meat", "Goat Meat", ["500g", "1kg", "2kg"], "pack"),
        ("Fresh Fish", "Tilapia", ["500g", "1kg", "2kg"], "pack"),
        ("Fresh Fish", "Nile Perch Fillet", ["500g", "1kg", "2kg"], "pack"),
        ("Fresh Fish", "Tuna Steaks", ["250g", "500g", "1kg"], "pack"),
        ("Farmers Choice", "Meatballs", ["250g", "500g", "1kg"], "pack"),
        ("Farmers Choice", "Ham Slices", ["200g", "400g", "800g"], "pack"),
    ])

    _variants(catalog, "Frozen Foods & Ice Cream", [
        ("McCain", "Frozen Chips", ["500g", "1kg", "2kg"], "pack"),
        ("McCain", "Frozen Peas", ["400g", "800g", "1kg"], "pack"),
        ("Various", "Frozen Mixed Vegetables", ["400g", "800g", "1kg"], "pack"),
        ("Various", "Frozen Broccoli Mix", ["400g", "800g", "1kg"], "pack"),
        ("Various", "Frozen Chicken Nuggets", ["400g", "800g", "1kg"], "pack"),
        ("Various", "Frozen Sausages", ["400g", "800g", "1kg"], "pack"),
        ("Various", "Frozen Pizza", ["350g", "420g", "500g"], "pack"),
        ("Various", "Frozen Fish Fillet", ["400g", "800g", "1kg"], "pack"),
        ("Creambell", "Ice Cream Vanilla", ["500ml", "1L", "2L"], "tub"),
        ("Creambell", "Ice Cream Chocolate", ["500ml", "1L", "2L"], "tub"),
        ("Creambell", "Ice Cream Strawberry", ["500ml", "1L", "2L"], "tub"),
        ("Cadbury", "Ice Cream Chocolate", ["500ml", "1L", "2L"], "tub"),
        ("Various", "Frozen Spring Rolls", ["250g", "500g", "1kg"], "pack"),
        ("Various", "Frozen Samosas", ["250g", "500g", "1kg"], "pack"),
    ])

    _variants(catalog, "Pet Care", [
        ("Purina", "Dog Chow", ["500g", "1.5kg", "3kg", "8kg"], "bag"),
        ("Kit Cat", "Dry Cat Food", ["500g", "1kg", "2kg"], "bag"),
        ("Purina", "Cat Chow", ["500g", "1.5kg", "3kg"], "bag"),
        ("Whiskas", "Dry Cat Food", ["450g", "1.2kg", "3kg"], "bag"),
        ("Whiskas", "Wet Cat Food Pouch", ["85g", "4x85g", "12x85g"], "pack"),
        ("Pedigree", "Dog Treats", ["200g", "400g", "800g"], "pack"),
        ("Various", "Dog Biscuits", ["250g", "500g", "1kg"], "pack"),
        ("Various", "Cat Litter", ["5L", "10L", "20L"], "bag"),
        ("Various", "Pet Shampoo", ["200ml", "400ml", "750ml"], "bottle"),
        ("Various", "Pet Food Bowl", ["1pc", "2pc", "4pc"], "piece"),
    ])

    _variants(catalog, "Health & Wellness", [
        ("Panadol", "Extra", ["16 Tablets", "24 Tablets", "32 Tablets"], "pack"),
        ("Panadol", "Advance", ["16 Tablets", "24 Tablets", "32 Tablets"], "pack"),
        ("Dettol", "Antiseptic Liquid", ["250ml", "500ml", "1L"], "bottle"),
        ("Savlon", "Antiseptic Liquid", ["250ml", "750ml", "2L"], "bottle"),
        ("Johnson's", "Cotton Buds", ["60s", "100s", "200s"], "pack"),
        ("Various", "Digital Thermometer", ["1pc", "2pc", "3pc"], "piece"),
        ("Various", "Plasters Assorted", ["20s", "40s", "80s"], "pack"),
        ("Oral-B", "Dental Floss", ["25m", "50m", "100m"], "piece"),
        ("Dettol", "Hand Sanitizer", ["50ml", "200ml", "500ml"], "bottle"),
        ("J&J", "First Aid Gauze", ["5s", "10s", "20s"], "pack"),
        ("Various", "Hand Gloves", ["10s", "50s", "100s"], "pack"),
        ("Various", "Face Masks", ["10s", "50s", "100s"], "pack"),
    ])

    _variants(catalog, "Stationery & General Merchandise", [
        ("Office Point", "A4 Exercise Books", ["96 Pages", "200 Pages", "300 Pages"], "pack"),
        ("Office Point", "Ball Pens Blue", ["5 Pack", "10 Pack", "50 Pack"], "pack"),
        ("Office Point", "Ball Pens Black", ["5 Pack", "10 Pack", "50 Pack"], "pack"),
        ("Faber Castell", "HB Pencils", ["6 Pack", "12 Pack", "24 Pack"], "pack"),
        ("Pelikan", "Colour Pencils", ["12 Pack", "24 Pack", "36 Pack"], "pack"),
        ("Office Point", "Permanent Marker Black", ["1pc", "3pc", "6pc"], "pack"),
        ("Office Point", "Permanent Marker Assorted", ["4pc", "8pc", "12pc"], "pack"),
        ("PaperOne", "A4 Printing Paper", ["500 Sheets", "1000 Sheets", "2500 Sheets"], "ream"),
        ("Veda", "My Big Crayons", ["6 Pack", "12 Pack", "24 Pack"], "pack"),
        ("Teepee", "A4 Laminated Book Cover", ["5 Pack", "10 Pack", "20 Pack"], "pack"),
        ("Office Point", "Moulding Clay", ["6 Pack", "12 Pack", "24 Pack"], "pack"),
        ("BIC", "Orange Fine Point Pens", ["3 Pack", "5 Pack", "10 Pack"], "pack"),
        ("BIC", "Twin Lady Razors", ["5 Pack", "10 Pack", "20 Pack"], "pack"),
        ("Various", "A4 Manila Folder", ["5 Pack", "10 Pack", "25 Pack"], "pack"),
    ])

    _variants(catalog, "Electronics & Small Appliances", [
        ("Various", "LED Bulb", ["5W", "9W", "12W", "18W"], "piece"),
        ("Various", "LED Bulb Cool White", ["9W", "12W", "15W"], "piece"),
        ("Various", "Extension Cable 4 Way", ["2m", "5m", "10m"], "piece"),
        ("Various", "Extension Cable 6 Way", ["2m", "5m", "10m"], "piece"),
        ("Various", "Phone Charging Cable USB-C", ["1m", "2m", "3m"], "piece"),
        ("Various", "Phone Charging Cable Lightning", ["1m", "2m", "3m"], "piece"),
        ("Various", "USB Wall Charger", ["10W", "20W", "30W", "65W"], "piece"),
        ("Ramtons", "Electric Kettle", ["1L", "1.7L", "2L"], "piece"),
        ("Ramtons", "Hand Blender", ["200W", "400W", "600W"], "piece"),
        ("Mika", "Toaster", ["2 Slice", "4 Slice", "6 Slice"], "piece"),
        ("Ramtons", "Sandwich Maker", ["750W", "1000W", "1200W"], "piece"),
        ("Philips", "Electric Iron", ["1000W", "1600W", "2200W"], "piece"),
        ("LG", "Microwave Oven", ["20L", "25L", "32L"], "piece"),
        ("Samsung", "Microwave Oven", ["20L", "25L", "32L"], "piece"),
        ("Von Hotpoint", "Blender", ["1.5L", "2L", "3L"], "piece"),
    ])

    return catalog
