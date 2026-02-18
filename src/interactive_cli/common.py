from InquirerPy import inquirer
from InquirerPy.separator import Separator
from InquirerPy.base.control import Choice

from src.commands import get_all_categories

TRANSFER_CHOICE = "__transfer_no_category__"


def _group_categories_by_type_and_parent(categories):
    grouped = {}
    for c in categories:
        ctype = (c.type or "unknown").lower()
        parent = c.parent_name or "Uncategorized"
        grouped.setdefault(ctype, {}).setdefault(parent, []).append(c)
    for ctype in grouped:
        for parent in grouped[ctype]:
            grouped[ctype][parent] = sorted(grouped[ctype][parent], key=lambda x: x.name.lower())
    return grouped


async def choose_category_tree(session, prompt_prefix="Select Category", default_type=None, restrict_to_default_type=False):
    cats = await get_all_categories(session)
    if not cats:
        return None

    grouped = _group_categories_by_type_and_parent(cats)
    available_types = sorted(grouped.keys())
    if restrict_to_default_type and default_type and default_type in available_types:
        available_types = [default_type]
    elif default_type and default_type in available_types:
        available_types = [default_type] + [t for t in available_types if t != default_type]

    selected_type = await inquirer.select(
        message=f"{prompt_prefix}: Select Type",
        choices=[Choice(value=t, name=t.upper()) for t in available_types]
        + [
            Choice(value=TRANSFER_CHOICE, name="TRANSFER (no category)"),
            Choice(value=None, name="Cancel"),
        ],
    ).execute_async()
    if not selected_type:
        return None
    if selected_type == TRANSFER_CHOICE:
        return TRANSFER_CHOICE

    tree_choices = []
    parent_names = sorted(grouped[selected_type].keys())
    for parent in parent_names:
        tree_choices.append(Separator(f"📁 {parent}"))
        children = grouped[selected_type][parent]
        for idx, child in enumerate(children):
            branch = "└─" if idx == len(children) - 1 else "├─"
            tree_choices.append(Choice(value=child, name=f"  {branch} {child.name}"))

    tree_choices.append(Choice(value=None, name="Back"))

    return await inquirer.select(
        message=f"{prompt_prefix}: Select Sub-Category ({selected_type.upper()})",
        choices=tree_choices,
    ).execute_async()
