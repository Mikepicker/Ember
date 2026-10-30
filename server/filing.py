"""Where a new note goes: one of the folders in a list edited in the app, picked by the 2B from what each holds,
unless the people and projects the note names already live in a single folder."""
import json
import re

import model

# the folders a new note can be filed into, until the list is changed in the app: one per line, "name: what goes in it"
FOLDERS = """work: the job and the company: clients, colleagues, products, projects, orders, deliveries, invoices
home: the house and what is in it: repairs, appliances, cleaning, garden, pets
money: personal finances: bills, bank, mortgage, savings, insurance, taxes
health: body and mind: doctors, appointments, exercise, sleep
family: parents, children, partner, relatives
friends: friends and social life
travel: trips and getting around: flights, trains, hotels, documents
food: recipes, cooking, restaurants
shopping: things to buy and gifts
learning: books, courses, talks, studying
hobbies: music, games, crafts, sport for fun
ideas: ideas and plans with no date"""

PROMPT = """You file personal notes. Pick the area of life the note belongs to,
and name its topic with one lowercase plural noun, the label you would write on a drawer."""

EXAMPLES = [
    ("Gym plan\nLegs on Monday, run on Wednesday", {"area": "health", "topic": "fitness"}),
    ("Electricity bill\nDue on the 5th, 82 EUR", {"area": "money", "topic": "bills"}),
    ("Risotto for Saturday\nArborio rice, saffron, parmesan", {"area": "food", "topic": "recipes"}),
]

# NovaX, DeltaWorks; Henrik mid-sentence. Not AI or TV: a note saying "AI" isn't about the other notes saying it
NAME = re.compile(r"\b(?=[A-Za-z]*[a-z])[A-Za-z]*[A-Z][A-Za-z]*[A-Z][A-Za-z]*\b|(?<=[a-z,] )[A-Z][a-z]+\b")
NOT_NAMES = {*"monday tuesday wednesday thursday friday saturday sunday january february march april may june july".split(),
             *"august september october november december eur usd am pm ok asap todo".split()}


def folders(text):
    """The folders in the list, {name: what goes in it}; "work/novax" is a folder inside work."""
    found = {}
    for line in text.splitlines():
        name, _, about = line.partition(":")
        name = re.sub(r"\s*/\s*", "/", name.strip().removeprefix("- ").strip())
        if re.fullmatch(r"([^\W_][^/\\]*/)*[^\W_][^/\\]*", name):  # each part starts with a letter or digit: no "..", no "_trash"
            found[name] = about.strip()
    return found


def names(text):
    """People, places and projects a note mentions, lowercased."""
    return {w.lower() for w in NAME.findall(text)} - NOT_NAMES


def pick(text, choices):
    """The 2B's pick of the folders in `choices`, {name: what goes in it}."""
    about = "\n".join(f"- {name}: {what}" if what else f"- {name}" for name, what in choices.items())
    messages = [{"role": "system", "content": f"{PROMPT}\nAreas:\n{about}"}]
    for note, answer in EXAMPLES:
        messages += [{"role": "user", "content": note}, {"role": "assistant", "content": json.dumps(answer)}]
    # the topic isn't used, but files notes better: 73 of the eval's 80 against 70 without it, 66 asked for a "folder"
    topic = {"type": "string", "pattern": "^[a-z]{3,15}$"}
    schema = {"type": "object", "properties": {"area": {"enum": list(choices)}, "topic": topic}, "required": ["area", "topic"]}
    return model.ask(messages + [{"role": "user", "content": text}], schema)["area"]


def known(text, others, choices):
    """The folder where the people and projects a note mentions already live, if it's a single one in the list.
    `others` are the other notes, (folder, text). A word counts as a name once any note wrote it as one, so "Henrik's site" and "kova" count too."""
    words = lambda t: set(re.findall(r"[a-z]+", t.lower()))
    wanted = names(text) | (words(text) & set().union(*(names(t) for _, t in others)))
    found = {folder for folder, t in others if wanted & words(t)}
    return found.pop() if len(found) == 1 and found <= set(choices) else None


def place(note, raw, others, choices):
    """The folder for a tidied note: the 2B's pick, unless its people and projects live elsewhere."""
    picked = pick(f"{note['title']}\n{note['body']}", choices)
    home = known(f"{note['title']}\n{note['body']}\n{raw}", others, choices)
    return home if home and not f"{picked}/".startswith(f"{home}/") else picked  # a note about Henrik goes where Henrik's notes are
