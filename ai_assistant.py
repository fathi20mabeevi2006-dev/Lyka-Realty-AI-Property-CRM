from database import get_all_properties, get_all_leads, get_dashboard_stats

def answer_question(question):
    question = question.lower().strip()

    properties = get_all_properties()
    leads = get_all_leads()
    stats = get_dashboard_stats()

    # Dashboard Stats
    if "dashboard" in question or "stats" in question:
        return f"""
📊 CRM Dashboard Snapshot

🏢 Total Properties: {stats['total_properties']}
🟢 Available: {stats['available']}
🔴 Sold: {stats['sold']}
🟠 Rented: {stats['rented']}
👥 Total Leads: {stats['total_leads']}
"""

    # How many leads
    if "how many leads" in question:
        return f"👥 You currently have {len(leads)} leads."

    # Available properties
    if "available" in question:
        available = [
            p for p in properties
            if str(p.get("status", "")).lower() == "available"
        ]
        return f"🟢 There are {len(available)} available properties."

    # Cheapest property
    if "cheapest" in question:
        cheapest = min(properties, key=lambda x: float(x.get("price", 0)))
        return (
            f"💰 Cheapest Property:\n\n"
            f"{cheapest['name']}\n"
            f"📍 {cheapest['location']}\n"
            f"💵 ₹{cheapest['price']}"
        )

    # Most expensive property
    if "expensive" in question:
        expensive = max(properties, key=lambda x: float(x.get("price", 0)))
        return (
            f"🏆 Most Expensive Property:\n\n"
            f"{expensive['name']}\n"
            f"📍 {expensive['location']}\n"
            f"💵 ₹{expensive['price']}"
        )

    # Location search
    locations = [
        "jumeirah",
        "dubai marina",
        "downtown dubai",
        "business bay",
        "palm jumeirah",
        "jvc",
        "al furjan"
    ]

    for loc in locations:
        if loc in question:
            results = [
                p for p in properties
                if loc.lower() in str(p.get("location", "")).lower()
            ]

            if not results:
                return f"No properties found in {loc.title()}."

            reply = f"🏠 Found {len(results)} properties in {loc.title()}:\n\n"

            for p in results[:10]:
                reply += (
                    f"• {p['name']} | "
                    f"₹{p['price']} | "
                    f"{p['bedrooms']} Bed | "
                    f"{p['location']}\n"
                )

            return reply

    # Bedroom search
    for bed in range(1, 8):
        if f"{bed} bedroom" in question or f"{bed} bed" in question:
            results = [
                p for p in properties
                if int(p.get("bedrooms", 0)) == bed
            ]

            reply = f"🏠 Found {len(results)} properties with {bed} bedrooms:\n\n"

            for p in results[:10]:
                reply += (
                    f"• {p['name']} | "
                    f"₹{p['price']} | "
                    f"{p['location']}\n"
                )

            return reply

    return """
🤖 I can help with:

• Dashboard stats
• How many leads
• Available properties
• Cheapest property
• Most expensive property
• Properties in Jumeirah
• Properties in Dubai Marina
• 2 bedroom properties
• 3 bedroom properties
"""