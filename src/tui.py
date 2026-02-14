
import asyncio
from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.styles import Style

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
        })

    def get_formatted_text(self):
        result = []
        for i, tx in enumerate(self.transactions):
            # Status Icon
            status_style = 'class:verified' if tx.is_verified else 'class:unverified'
            status_icon = "✅" if tx.is_verified else "  "
            
            # Category
            cat_str = "Uncategorized"
            if tx.category:
                if tx.category.parent_name:
                    cat_str = f"{tx.category.parent_name} > {tx.category.name}"
                else:
                    cat_str = tx.category.name
            
            # Confidence
            conf_str = ""
            if tx.confidence_score is not None and not tx.is_verified:
                val = int(tx.confidence_score * 100)
                conf_str = f"({val}%) "
            
            # Row styling
            style = 'class:selected' if i == self.selected_index else ''
            
            # Construct line
            # Date | Description | Amount | Confidence Category
            line = f"{status_icon} {tx.date.strftime('%Y-%m-%d')} | {tx.description[:25]:<25} | {tx.amount:>8.2f} | {conf_str}{cat_str}"
            
            result.append((style, line + '\n'))
        return result

    def get_header_text(self):
        verified = sum(1 for t in self.transactions if t.is_verified)
        total = len(self.transactions)
        return [('class:header', f" Reviewing Transactions: {verified}/{total} Verified ")]

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
            # Toggle? Or just verify? Review usually means verify.
            # Let's toggle for flexibility, or strictly verify?
            # User said: "simple enter/space ... should set it as approved"
            # So setting to True.
            
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
        footer = Window(content=FormattedTextControl(self.get_footer_text), height=1)
        
        root_container = HSplit([
            header,
            body,
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
