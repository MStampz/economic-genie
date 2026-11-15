"""Built-in knowledge that works for every group out of the box.

KEYWORDS: words and well-known payees that say what a payment is for. They are tried after the
group's own rules, its learned payees and the bank's category, so a family can always overrule them.
Categories named here are the built-in ones (see app.core.categories.DEFAULT_CATEGORIES); an entry
whose category is missing is ignored.

BANK_ALIASES: the bank's category names that mean one of ours ("Flights" -> "Travel expenses").
UNINFORMATIVE: bank categories that only say how money moved ("Transfers out"), so the text decides.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Keyword:
    pattern: re.Pattern
    category: str
    direction: str = "any"  # "out" (money out only), "in" (money in only) or "any"


def _k(words: str, category: str, direction: str = "any") -> Keyword:
    """words: alternatives separated by |, matched as whole words in the folded text."""
    return Keyword(re.compile(r"(?<![a-z0-9])(" + words + r")(?![a-z0-9])"), category, direction)


# Order matters: the first match wins, so specific entries come before general ones.
KEYWORDS: list[Keyword] = [
    # Income
    _k(r"salary|wages?|payroll|pay ?slip", "Salary", "in"),
    _k(r"interest paid|credit interest|bonus interest", "Interest", "in"),
    # Housing
    _k(r"rent|managed pm|property management|real estate", "Rent", "out"),
    _k(
        r"agl|origin energy|energyaustralia|energy australia|red energy|alinta|simply energy|powershop|lumo"
        r"|momentum energy|tango energy|ovo energy|south east water|yarra valley water|city west water"
        r"|sydney water|electricity|gas bill|water bill",
        "Utilities",
    ),
    # Food and drink (takeaway apps before the plain ride-share "uber")
    _k(
        r"uber ?eats|doordash|menulog|deliveroo|mcdonald'?s?|kfc|hungry jacks?|domino'?s?|guzman|grill'?d"
        r"|nando'?s|subway|pizza|sushi|restaurant|bistro|takeaway|take away|kebab|burger",
        "Restaurants & takeaway",
    ),
    _k(r"cafe|caffe|coffee|espresso|roasters?|bakery|patisserie", "Cafe & coffee"),
    _k(
        r"dan murphy'?s?|bws|liquorland|first choice liquor|vintage cellars|liquor|cellars?|uncorked?|winery"
        r"|bottle ?shop|wine",
        "Alcohol",
    ),
    _k(
        r"woolworths|coles|aldi|iga|foodworks|harris farm|costco|supermarket|grocer|netto|rema 1000|fotex|lidl"
        r"|irma|meny",
        "Groceries",
    ),
    # Transport
    _k(r"linkt|citylink|eastlink|transurban|wilson parking|secure parking|care park|parking|toll", "Parking & tolls"),
    _k(r"uber|didi|ola cabs|13cabs|taxi|myki|opal|ptv|metro trains|translink", "Taxis & ride shares"),
    _k(
        r"vicroads|service nsw|rego|car wash|carwash|mechanic|tyres?|repco|supercheap auto"
        r"|autobarn|ultra tune|mycar|volkswagen|toyota service",
        "Vehicle expenses",
    ),
    _k(
        r"bp|shell|caltex|ampol|7-eleven|7 eleven|united petroleum|puma energy|liberty oil|metro petroleum|fuel"
        r"|petrol",
        "Fuel",
    ),
    # Bills
    _k(
        r"telstra|optus|vodafone|aussie broadband|tpg|iinet|belong|amaysim|boost mobile|superloop|exetel|dodo"
        r"|telmore|yousee|telia|telenor|mobile plan|nbn",
        "Phone & internet",
    ),
    _k(
        r"medibank|bupa|hcf|nib|ahm|hbf|aami|allianz|budget direct|youi|nrma|racv insurance|qbe|suncorp"
        r"|insurance|insure",
        "Insurance",
    ),
    _k(
        r"netflix|spotify|disney ?plus|disney\+|stan\.com|binge|kayo|foxtel|youtube premium|apple\.com/bill"
        r"|audible|prime video|amazon prime|tv2 play|tv2 dk|viaplay|hbo|paramount|openai|chatgpt|anthropic"
        r"|claude\.ai|linkedin|adobe|dropbox|icloud|patreon|subscription",
        "Subscriptions",
    ),
    _k(r"council|fines victoria|fines vic|revenue nsw|ato|australian taxation|passport", "Government"),
    _k(
        r"chemist warehouse|chemist|pharmacy|priceline|terry white|dental|dentist|physio|clinic|medical"
        r"|hospital|pathology|optometrist|specsavers",
        "Medical",
    ),
    # Personal
    _k(
        r"hairdress\w*|barber|nails?|beauty|salon|day spa|massage|revo fitness|anytime fitness|f45|goodlife"
        r"|jetts|snap fitness|gym|fitness",
        "Personal care",
    ),
    _k(r"vet|vets|veterinary|petbarn|petstock|pet stock|dog|dogs|puppy|pet", "Pets"),
    _k(r"compass|com\*|school|schools|tuition|childcare|kindergarten|kinder|oshc", "Education"),
    _k(r"bunnings|mitre 10|home hardware|hardware|ifix|plumb\w*|electrician|handyman", "Home improvements"),
    _k(r"ikea|freedom furniture|adairs|bed bath|temple & webster|homeware|kitchen warehouse", "Homeware"),
    _k(r"jb hi-?fi|harvey norman|the good guys|officeworks|apple store|samsung|dick smith", "Electronics & technology"),
    _k(
        r"uniqlo|cotton on|h&m|zara|country road|rm williams|carhartt|nike|adidas|clothing|apparel",
        "Clothing & accessories",
    ),
    _k(
        r"qantas|virgin australia|jetstar|rex airlines|airbnb|booking\.com|expedia|hotel|motel|hostel"
        r"|travelex|currency exchange|melbourne currency|flight centre|resort|resor",
        "Travel expenses",
    ),
    _k(
        r"ticketek|ticketmaster|eventbrite|moshtix|hoyts|village cinemas|cinema|museum|zoo|aquarium",
        "Attractions & events",
    ),
    _k(r"amazon|kmart|target|big w|myer|david jones|ebay|etsy|temu|shein", "Other shopping"),
    _k(r"atm|cash withdrawal", "Cash", "out"),
    _k(r"fee|fees|charge|dir chg", "Fees", "out"),
    _k(r"loan repayment|mortgage|home loan|afterpay|zip pay|humm", "Loans", "out"),
]

BANK_ALIASES: dict[str, str] = {
    "income": "Salary",
    "wages": "Salary",
    "investment income": "Other income",
    "flights": "Travel expenses",
    "accommodation": "Travel expenses",
    "holidays": "Travel expenses",
    "public transport": "Taxis & ride shares",
    "hobbies": "Attractions & events",
    "entertainment": "Attractions & events",
    "sport & fitness": "Personal care",
    "health & fitness": "Personal care",
    "pharmacy": "Medical",
    "education": "Education",
    "childcare": "Education",
    "rent": "Rent",
    "home": "Homeware",
    "hardware": "Home improvements",
    "credit card repayments": "Internal transfers",
}

UNINFORMATIVE: set[str] = {
    "",
    "uncategorised",
    "uncategorized",
    "transfers out",
    "transfers in",
    "transfer",
    "transfers",
    "other",
    "miscellaneous",
    "general",
}

# When nothing else is known, money in that the bank called a transfer in is income of some sort.
FALLBACK_IN: dict[str, str] = {"transfers in": "Other income"}
