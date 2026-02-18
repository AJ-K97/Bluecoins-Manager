
import textwrap
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.styles import Style
from src.commands import format_category_label, get_transaction_category_display


class TransactionReviewApp:
    MAX_DESC_LEN = 28
    MAX_CAT_LEN = 36
    DETAILS_WIDTH = 98

    def __init__(self, transactions, session, update_callback=None):
        self.transactions = transactions
        self.session = session
        self.selected_index = 0
        self.update_callback = update_callback  # Async callback to update DB

        # Visual tokens used consistently across header/table/details/footer.
        self.style = Style.from_dict({
            'title': 'bg:#1d4ed8 fg:#f8fafc bold',
            'meta': 'bg:#dbeafe fg:#1e3a8a',
            'divider': 'fg:#334155',
            'table_header': 'fg:#e2e8f0 bold',
            'row_odd': 'fg:#cbd5e1',
            'row_even': 'fg:#94a3b8',
            'selected_row': 'bg:#1e293b fg:#f8fafc bold',
            'verified': 'fg:#22c55e bold',
            'unverified': 'fg:#f59e0b bold',
            'expense': 'fg:#fb7185',
            'income': 'fg:#34d399',
            'transfer': 'fg:#38bdf8',
            'cat': 'fg:#e2e8f0',
            'muted': 'fg:#94a3b8',
            'confidence_high': 'fg:#22c55e',
            'confidence_medium': 'fg:#f59e0b',
            'confidence_low': 'fg:#f87171',
            'details_title': 'fg:#38bdf8 bold',
            'details_text': 'fg:#e2e8f0',
            'footer': 'bg:#e2e8f0 fg:#0f172a',
            'hotkey': 'bg:#bfdbfe fg:#1e3a8a bold',
        })

    @staticmethod
    def _truncate(text, width):
        return textwrap.shorten((text or "").strip() or "-", width=width, placeholder="...")

    @staticmethod
    def _safe_percent(score):
        if score is None:
            return " --"
        try:
            clamped = max(0.0, min(1.0, float(score)))
        except (TypeError, ValueError):
            return " --"
        return f"{int(clamped * 100):>3}"

    @staticmethod
    def _confidence_class(score):
        if score is None:
            return "class:muted"
        if score >= 0.85:
            return "class:confidence_high"
        if score >= 0.60:
            return "class:confidence_medium"
        return "class:confidence_low"

    def _base_row_class(self, row_index):
        if row_index == self.selected_index:
            return "class:selected_row"
        if row_index % 2 == 0:
            return "class:row_even"
        return "class:row_odd"

    def _type_info(self, tx):
        if tx.type == "income":
            return "IN ", "class:income"
        if tx.type == "transfer":
            return "XFR", "class:transfer"
        return "OUT", "class:expense"

    def get_table_text(self):
        if not self.transactions:
            return [("class:muted", "No transactions loaded.\n")]

        result = [
            (
                "class:table_header",
                " ST  TYP DATE       DESCRIPTION                    AMOUNT      CONF  CATEGORY\n",
            )
        ]
        for i, tx in enumerate(self.transactions):
            base_style = self._base_row_class(i)
            status_style = "class:verified" if tx.is_verified else "class:unverified"
            status_text = "OK " if tx.is_verified else "AI "
            tx_type, type_class = self._type_info(tx)

            cat_str = "Uncategorized"
            parent_name, cat_name = get_transaction_category_display(tx)
            cat_type = tx.category.type if tx.category else tx.type
            cat_str = self._truncate(
                format_category_label(parent_name, cat_name, cat_type),
                self.MAX_CAT_LEN,
            )

            conf_score = tx.confidence_score if not tx.is_verified else 1.0
            conf_val = self._safe_percent(conf_score)
            conf_style = self._confidence_class(conf_score)
            desc = self._truncate(tx.description, self.MAX_DESC_LEN)

            result.append((f"{base_style} {status_style}", f" {status_text}"))
            result.append((f"{base_style} {type_class}", f" {tx_type} "))
            result.append((base_style, f"{tx.date.strftime('%Y-%m-%d')} "))
            result.append((base_style, f"{desc:<30} "))
            result.append((f"{base_style} {type_class}", f"{tx.amount:>10.2f} "))
            result.append((f"{base_style} {conf_style}", f"{conf_val}% "))
            result.append((f"{base_style} class:cat", f"{cat_str}\n"))
        return result

    def get_header_text(self):
        verified = sum(1 for t in self.transactions if t.is_verified)
        total = len(self.transactions)
        pending = max(total - verified, 0)
        width = 20
        done = int((verified / total) * width) if total else 0
        bar = f"[{'#' * done}{'-' * (width - done)}]"
        pct = int((verified / total) * 100) if total else 0
        return [
            ("class:title", " Bluecoins Manager  "),
            ("class:title", "Transaction Review"),
            ("", "\n"),
            (
                "class:meta",
                f" Verified {verified}/{total} | Pending {pending} | Progress {bar} {pct:>3}% ",
            ),
        ]

    def get_details_text(self):
        if not self.transactions:
            return []
        tx = self.transactions[self.selected_index]
        
        # Get latest memory
        mem = None
        if hasattr(tx, 'memory_entries') and tx.memory_entries:
            # Assuming ordered or just take last
            # In database logic, back_populates list might not be ordered unless specified.
            # But usually append adds to end.
            mem = tx.memory_entries[-1]

        reason = mem.ai_reasoning if mem and mem.ai_reasoning else "No AI reasoning recorded."
        reflection = mem.reflection if mem and mem.reflection else "No reflection notes."
        parent_name, cat_name = get_transaction_category_display(tx)
        cat_type = tx.category.type if tx.category else tx.type
        category = format_category_label(parent_name, cat_name, cat_type)
        confidence = self._safe_percent(tx.confidence_score)

        lines = [
            ("class:details_title", " Details "),
            ("class:muted", f"- tx_id={tx.id} | {tx.date.strftime('%Y-%m-%d')} | confidence={confidence}%\n"),
            ("class:details_text", f" Description: {self._truncate(tx.description, self.DETAILS_WIDTH)}\n"),
            ("class:details_text", f" Note: {self._truncate(getattr(tx, 'note', None) or '-', self.DETAILS_WIDTH)}\n"),
            ("class:details_text", f" Category: {category}\n"),
            ("class:details_text", f" AI Reasoning: {self._truncate(reason, self.DETAILS_WIDTH)}\n"),
            ("class:details_text", f" Reflection: {self._truncate(reflection, self.DETAILS_WIDTH)}\n"),
        ]
        return lines

    def get_footer_text(self):
        return [
            ("class:footer", " "),
            ("class:hotkey", "Up/Down"),
            ("class:footer", " navigate  "),
            ("class:hotkey", "Space/Enter"),
            ("class:footer", " verify  "),
            ("class:hotkey", "M"),
            ("class:footer", " modify category  "),
            ("class:hotkey", "N"),
            ("class:footer", " add/edit note  "),
            ("class:hotkey", "C"),
            ("class:footer", " coach model  "),
            ("class:hotkey", "D"),
            ("class:footer", " discuss decision  "),
            ("class:hotkey", "R"),
            ("class:footer", " reflect why correct  "),
            ("class:hotkey", "Del"),
            ("class:footer", " delete  "),
            ("class:hotkey", "Q"),
            ("class:footer", " exit "),
        ]

    async def run_async(self):
        kb = KeyBindings()

        @kb.add('q')
        def _(event):
            event.app.exit(result=None)

        @kb.add('up')
        def _(event):
            if not self.transactions:
                return
            self.selected_index = max(0, self.selected_index - 1)

        @kb.add('down')
        def _(event):
            if not self.transactions:
                return
            self.selected_index = min(len(self.transactions) - 1, self.selected_index + 1)

        @kb.add('space')
        @kb.add('enter')
        async def _(event):
            if not self.transactions:
                return
            tx = self.transactions[self.selected_index]
            
            if not tx.is_verified:
                tx.is_verified = True
                if self.update_callback:
                    await self.update_callback(tx, 'verify')
            
            # Auto-advance
            self.selected_index = min(len(self.transactions) - 1, self.selected_index + 1)

        @kb.add('m')
        def _(event):
            if not self.transactions:
                return
            event.app.exit(result=('modify', self.transactions[self.selected_index]))

        @kb.add('n')
        def _(event):
            if not self.transactions:
                return
            event.app.exit(result=('note', self.transactions[self.selected_index]))

        @kb.add('c')
        def _(event):
            if not self.transactions:
                return
            event.app.exit(result=('coach', self.transactions[self.selected_index]))

        @kb.add('d')
        def _(event):
            if not self.transactions:
                return
            event.app.exit(result=('discuss', self.transactions[self.selected_index]))

        @kb.add('r')
        def _(event):
            if not self.transactions:
                return
            event.app.exit(result=('reflect', self.transactions[self.selected_index]))

        @kb.add('delete')
        def _(event):
            if not self.transactions:
                return
            event.app.exit(result=('delete', self.transactions[self.selected_index]))

        # Layout
        header = Window(content=FormattedTextControl(self.get_header_text), height=2, wrap_lines=False)
        body = Window(content=FormattedTextControl(self.get_table_text), wrap_lines=False)
        details_height = 7
        details = Window(content=FormattedTextControl(self.get_details_text), height=details_height, wrap_lines=True)
        footer = Window(content=FormattedTextControl(self.get_footer_text), height=1, wrap_lines=False)

        divider = Window(height=1, char='─', style='class:divider')

        root_container = HSplit([
            header,
            body,
            divider,
            details,
            footer
        ])

        self.app = Application(
            layout=Layout(root_container),
            key_bindings=kb,
            style=self.style,
            full_screen=True,
            mouse_support=True
        )

        return await self.app.run_async()
