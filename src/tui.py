
import asyncio
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.styles import Style
from src.commands import format_category_label, get_transaction_category_display

class TransactionReviewApp:
    def __init__(self, transactions, session, update_callback=None):
        self.transactions = transactions
        self.session = session
        self.selected_index = 0
        self.update_callback = update_callback  # Async callback to update DB
        
        # Style
        self.style = Style.from_dict({
            'selected': 'reverse',
            'verified': 'fg:ansigreen',
            'unverified': 'fg:ansired',
            'header': 'bg:ansiblue fg:white bold',
            'footer': 'bg:ansigray fg:black',
            'expense': 'fg:#ff8888', # Muted Red
            'income': 'fg:#88ff88',  # Muted Green
            'transfer': 'fg:#8888ff', # Muted Blue
        })

    def get_formatted_text(self):
        result = []
        for i, tx in enumerate(self.transactions):
            # Base style
            base_style = 'class:selected' if i == self.selected_index else ''
            
            # Type Style
            if tx.type == 'income':
                type_class = 'class:income'
                type_icon = "⬆"
            elif tx.type == 'transfer':
                type_class = 'class:transfer'
                type_icon = "↔"
            else:
                type_class = 'class:expense'
                type_icon = "⬇"
                
            icon_style = f"{base_style} {type_class}"
            
            # Status
            status_style = 'class:verified' if tx.is_verified else 'class:unverified'
            status_text = "✅" if tx.is_verified else "🤖" # User verified vs AI/Unverified
            
            cat_str = "Uncategorized"
            parent_name, cat_name = get_transaction_category_display(tx)
            cat_type = tx.category.type if tx.category else tx.type
            cat_str = format_category_label(parent_name, cat_name, cat_type)
            
            conf_str = ""
            if tx.confidence_score is not None and not tx.is_verified:
                val = int(tx.confidence_score * 100)
                conf_str = f"({val}%) "

            # Construct line segments
            result.append((f"{base_style} {status_style}", f"{status_text} "))
            result.append((icon_style, f"{type_icon} "))
            result.append((base_style, f"{tx.date.strftime('%Y-%m-%d')} | "))
            result.append((base_style, f"{tx.description[:25]:<25} | "))
            result.append((icon_style, f"{tx.amount:>8.2f} "))
            result.append((base_style, f"| {conf_str}{cat_str}\n"))
        return result

    def get_header_text(self):
        verified = sum(1 for t in self.transactions if t.is_verified)
        total = len(self.transactions)
        return [('class:header', f" Reviewing Transactions: {verified}/{total} Verified ")]

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
            
        reason = mem.ai_reasoning if mem and mem.ai_reasoning else "No reasoning available."
        reflection = mem.reflection if mem and mem.reflection else ""
        
        text_out = f" AI Reasoning: {reason}"
        if reflection:
            text_out += f"\n 🧠 Reflection: {reflection}"
            
        return [('', text_out)]

    def get_footer_text(self):
        return [('class:footer', " [Up/Down] Nav  [Space/Enter] Verify  [M] Modify Cat  [Del] Delete  [q] Done ")]

    async def run_async(self):
        kb = KeyBindings()

        @kb.add('q')
        def _(event):
            event.app.exit(result=None)

        @kb.add('up')
        def _(event):
            self.selected_index = max(0, self.selected_index - 1)

        @kb.add('down')
        def _(event):
            self.selected_index = min(len(self.transactions) - 1, self.selected_index + 1)

        @kb.add('space')
        @kb.add('enter')
        async def _(event):
            tx = self.transactions[self.selected_index]
            
            if not tx.is_verified:
                tx.is_verified = True
                if self.update_callback:
                    await self.update_callback(tx, 'verify')
            
            # Auto-advance
            self.selected_index = min(len(self.transactions) - 1, self.selected_index + 1)

        @kb.add('m')
        def _(event):
            event.app.exit(result=('modify', self.transactions[self.selected_index]))

        @kb.add('delete')
        def _(event):
            event.app.exit(result=('delete', self.transactions[self.selected_index]))

        # Layout
        body = Window(content=FormattedTextControl(self.get_formatted_text))
        header = Window(content=FormattedTextControl(self.get_header_text), height=1, align=WindowAlign.CENTER)
        # Details pane
        details_height = 4
        details = Window(content=FormattedTextControl(self.get_details_text), height=details_height, wrap_lines=True)
        footer = Window(content=FormattedTextControl(self.get_footer_text), height=1)
        
        # Divider
        divider = Window(height=1, char='-', style='class:footer')

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
