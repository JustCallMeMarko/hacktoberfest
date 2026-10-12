"""A desktop calculator with a compact basic mode and an expanded scientific mode.

Basic mode (the window at its normal size) runs left to right, so 2 + 3 × 4
equals 20, and it keeps numbers as decimals so 0.1 + 0.2 is 0.3.

Scientific mode (the window expanded) uses standard precedence and parentheses,
so 2 + 3 × 4 equals 14. Trig functions use degrees until you switch to radians.
"""

import math
import re
import sys
from decimal import ROUND_HALF_UP, Decimal, DecimalException

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

OPERATOR_SYMBOLS = {"+": "+", "-": "−", "*": "×", "/": "÷"}
MAX_DIGITS = 12
NORMAL_WIDTH = 340
EXPANDED_WIDTH = 680
WINDOW_HEIGHT = 560

_NUMBER_RE = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_FUNCTIONS = ("asin", "acos", "atan", "sin", "cos", "tan", "sqrt", "log", "ln", "abs")
_VALUE_STARTERS = set(_FUNCTIONS) | {"pi", "e", "lparen", "exp10"}
_VALUE_ENDERS = {"pi", "e", "square", "fact", "recip", "rparen"}

_RENDER = {
    "sin": "sin(",
    "cos": "cos(",
    "tan": "tan(",
    "asin": "asin(",
    "acos": "acos(",
    "atan": "atan(",
    "ln": "ln(",
    "log": "log(",
    "sqrt": "sqrt(",
    "abs": "abs(",
    "square": "^2",
    "power": "^",
    "fact": "!",
    "recip": "^(-1)",
    "pi": "pi",
    "e": "e",
    "lparen": "(",
    "rparen": ")",
    "exp10": "10^(",
    "+": "+",
    "-": "-",
    "*": "*",
    "/": "/",
}
_PRETTY = {
    "sin": "sin(",
    "cos": "cos(",
    "tan": "tan(",
    "asin": "asin(",
    "acos": "acos(",
    "atan": "atan(",
    "ln": "ln(",
    "log": "log(",
    "sqrt": "√(",
    "abs": "abs(",
    "square": "²",
    "power": "^",
    "fact": "!",
    "recip": "⁻¹",
    "pi": "π",
    "e": "e",
    "lparen": "(",
    "rparen": ")",
    "exp10": "10^(",
    "+": " + ",
    "-": " − ",
    "*": " × ",
    "/": " ÷ ",
}


def format_decimal(value: Decimal) -> str:
    """Render a decimal without binary-float noise or trailing zeros."""
    try:
        quantized = value.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
    except DecimalException:
        return f"{value:.6e}"

    if quantized == 0 and value != 0:
        return f"{value:.6e}"

    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"

    digits = text.replace("-", "").replace(".", "")
    if len(digits) > MAX_DIGITS:
        return f"{value:.6e}"
    return text


def format_float(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("not finite")
    try:
        decimal_value = Decimal(format(value, ".12g"))
    except DecimalException:
        return format(value, ".6e")
    return format_decimal(decimal_value)


def _factorial(value: float) -> float:
    if value < 0 or abs(value - round(value)) > 1e-9:
        raise ValueError("factorial")
    number = int(round(value))
    if number > 170:
        raise ValueError("factorial")
    return float(math.factorial(number))


class ExpressionParser:
    """Small arithmetic parser for scientific mode. Standard precedence, ^ is right-associative."""

    def __init__(self, text: str, degrees: bool) -> None:
        self.text = text
        self.n = len(text)
        self.i = 0
        self.degrees = degrees

    def parse(self) -> float:
        if not self.text:
            raise ValueError("empty")
        value = self._expression()
        if self.i != self.n:
            raise ValueError("trailing input")
        if isinstance(value, complex) or not math.isfinite(value):
            raise ValueError("not finite")
        return value

    def _peek(self) -> str:
        if self.i >= self.n:
            return ""
        return self.text[self.i]

    def _expression(self) -> float:
        value = self._term()
        while self._peek() in {"+", "-"}:
            operator = self._peek()
            self.i += 1
            right = self._term()
            value = value + right if operator == "+" else value - right
        return value

    def _term(self) -> float:
        value = self._power()
        while self._peek() in {"*", "/"}:
            operator = self._peek()
            self.i += 1
            right = self._power()
            if operator == "/" and right == 0:
                raise ZeroDivisionError
            value = value * right if operator == "*" else value / right
        return value

    def _power(self) -> float:
        base = self._unary()
        if self._peek() != "^":
            return base
        self.i += 1
        exponent = self._power()
        try:
            value = base ** exponent
        except (OverflowError, ZeroDivisionError, ValueError):
            raise
        if isinstance(value, complex) or not math.isfinite(value):
            raise ValueError("bad power")
        return value

    def _unary(self) -> float:
        if self._peek() == "-":
            self.i += 1
            return -self._unary()
        if self._peek() == "+":
            self.i += 1
            return self._unary()
        return self._postfix()

    def _postfix(self) -> float:
        value = self._primary()
        while self._peek() == "!":
            self.i += 1
            value = _factorial(value)
        return value

    def _primary(self) -> float:
        if self._peek() == "(":
            self.i += 1
            value = self._expression()
            if self._peek() != ")":
                raise ValueError("missing )")
            self.i += 1
            return value
        if self.text.startswith("pi", self.i):
            self.i += 2
            return math.pi
        for name in _FUNCTIONS:
            if self.text.startswith(name + "(", self.i):
                self.i += len(name) + 1
                argument = self._expression()
                if self._peek() != ")":
                    raise ValueError("missing )")
                self.i += 1
                return self._call(name, argument)
        if self._peek() == "e":
            self.i += 1
            return math.e
        return self._number()

    def _number(self) -> float:
        match = re.match(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", self.text[self.i :])
        if not match:
            raise ValueError("expected number")
        self.i += match.end()
        return float(match.group())

    def _call(self, name: str, argument: float) -> float:
        if name in {"sin", "cos", "tan"}:
            if name == "tan" and self._tangent_undefined(argument):
                raise ValueError("tan undefined")
            if self.degrees:
                argument = math.radians(argument)
        try:
            if name == "ln":
                result = math.log(argument)
            elif name == "log":
                result = math.log10(argument)
            elif name == "sqrt":
                result = math.sqrt(argument)
            elif name == "abs":
                result = abs(argument)
            else:
                result = getattr(math, name)(argument)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if name in {"asin", "acos", "atan"} and self.degrees:
            result = math.degrees(result)
        return result

    def _tangent_undefined(self, argument: float) -> bool:
        degrees = argument if self.degrees else math.degrees(argument)
        reduced = abs(degrees) % 180
        return abs(reduced - 90) < 1e-8


def evaluate_expression(text: str, degrees: bool) -> float:
    return ExpressionParser(text, degrees).parse()


class CalculatorEngine:
    """Immediate-execution calculator state for basic mode."""

    def __init__(self) -> None:
        self.current = "0"
        self.stored: Decimal | None = None
        self.operator: str | None = None
        self.fresh = True
        self.error = False
        self.history = ""

    def input_digit(self, digit: str) -> None:
        if self.error:
            self.clear()
        if self.fresh:
            self.current = digit
            self.fresh = False
            if self.operator is None:
                self.history = ""
            return
        if self.current == "0":
            self.current = digit
            return
        if self._digit_count() >= MAX_DIGITS:
            return
        self.current += digit

    def input_decimal(self) -> None:
        if self.error:
            self.clear()
        if self.fresh:
            self.current = "0."
            self.fresh = False
            if self.operator is None:
                self.history = ""
            return
        if "." not in self.current:
            self.current += "."

    def input_operator(self, operator: str) -> None:
        if self.error:
            return
        if self.operator and not self.fresh:
            self.equals()
            if self.error:
                return
        self.stored = Decimal(self.current)
        self.operator = operator
        self.fresh = True
        self.history = ""

    def equals(self) -> None:
        if self.error or self.operator is None or self.stored is None:
            return
        try:
            result = self._apply(self.stored, self.operator, Decimal(self.current))
        except DecimalException:
            self._fail()
            return

        symbol = OPERATOR_SYMBOLS[self.operator]
        self.history = f"{format_decimal(self.stored)} {symbol} {self.current} ="
        self.current = format_decimal(result)
        self.stored = result
        self.operator = None
        self.fresh = True

    def percent(self) -> None:
        if self.error:
            return
        try:
            value = Decimal(self.current) / Decimal(100)
        except DecimalException:
            self._fail()
            return
        self.current = format_decimal(value)
        self.fresh = True

    def toggle_sign(self) -> None:
        if self.error:
            return
        if self.current.startswith("-"):
            self.current = self.current[1:] or "0"
        elif self.current not in {"0", "0."}:
            self.current = f"-{self.current}"

    def backspace(self) -> None:
        if self.error or self.fresh:
            return
        self.current = self.current[:-1]
        if self.current in {"", "-"}:
            self.current = "0"
            self.fresh = True

    def clear(self) -> None:
        self.current = "0"
        self.stored = None
        self.operator = None
        self.fresh = True
        self.error = False
        self.history = ""

    def expression_text(self) -> str:
        if self.history:
            return self.history
        if self.operator is None or self.stored is None:
            return ""
        symbol = OPERATOR_SYMBOLS[self.operator]
        left = format_decimal(self.stored)
        if self.fresh:
            return f"{left} {symbol}"
        return f"{left} {symbol} {self.current}"

    def display_text(self) -> str:
        if self.error:
            return "Error"
        return self.current

    def _apply(self, left: Decimal, operator: str, right: Decimal) -> Decimal:
        if operator == "+":
            return left + right
        if operator == "-":
            return left - right
        if operator == "*":
            return left * right
        if operator == "/":
            return left / right
        raise DecimalException(f"Unknown operator: {operator}")

    def _fail(self) -> None:
        self.error = True
        self.current = "0"
        self.stored = None
        self.operator = None
        self.fresh = True
        self.history = ""

    def _digit_count(self) -> int:
        return len(self.current.replace("-", "").replace(".", ""))


class ScientificEngine:
    """Expression calculator used while the window is expanded."""

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.result = ""
        self.error = False
        self.degrees = True
        self.just_evaluated = False

    def input_digit(self, digit: str) -> None:
        if self.error or self.just_evaluated:
            self.tokens = []
            self.error = False
            self.just_evaluated = False
        if self.tokens and self._is_number_token(self.tokens[-1]) and "e" not in self.tokens[-1].lower():
            if self.tokens[-1] in {"0", "-0"}:
                self.tokens[-1] = f"-{digit}" if self.tokens[-1].startswith("-") else digit
            else:
                self.tokens[-1] += digit
            return
        self.tokens.append(digit)

    def input_decimal(self) -> None:
        if self.error or self.just_evaluated:
            self.tokens = ["0."]
            self.error = False
            self.just_evaluated = False
            return
        if self.tokens and self._is_number_token(self.tokens[-1]) and "." not in self.tokens[-1]:
            self.tokens[-1] += "."
            return
        if self.tokens and self.tokens[-1].endswith("."):
            return
        self.tokens.append("0.")

    def input_operator(self, operator: str) -> None:
        if self.error:
            return
        if self.just_evaluated:
            self.tokens = [self.result] if self.result else []
            self.just_evaluated = False
        if not self.tokens:
            if operator == "-":
                self.tokens.append("-")
            return
        if self.tokens[-1] in {"+", "-", "*", "/", "power"}:
            self.tokens[-1] = operator
            return
        self.tokens.append(operator)

    def input_function(self, name: str) -> None:
        if self.error:
            self.clear()
        if self.just_evaluated and self.result:
            self.tokens = [name, self.result, "rparen"]
            self.just_evaluated = False
            self.equals()
            return
        if self.just_evaluated:
            self.tokens = []
            self.just_evaluated = False
        self.tokens.append(name)

    def input_postfix(self, token: str) -> None:
        if self.error:
            return
        if self.just_evaluated and self.result:
            self.tokens = [self.result, token]
            self.just_evaluated = False
            self.equals()
            return
        if not self.tokens:
            return
        self.tokens.append(token)

    def input_constant(self, token: str) -> None:
        if self.error or self.just_evaluated:
            self.tokens = []
            self.error = False
            self.just_evaluated = False
        self.tokens.append(token)

    def input_paren(self, token: str) -> None:
        if self.error or self.just_evaluated:
            self.tokens = []
            self.error = False
            self.just_evaluated = False
        self.tokens.append(token)

    def percent(self) -> None:
        if self.error:
            return
        if self.just_evaluated and self.result:
            self.tokens = [self.result]
            self.just_evaluated = False
        if not self.tokens or not self._is_number_token(self.tokens[-1]):
            return
        try:
            value = Decimal(self.tokens[-1]) / Decimal(100)
        except DecimalException:
            self._fail()
            return
        self.tokens[-1] = format_decimal(value)

    def toggle_sign(self) -> None:
        if self.error:
            return
        if self.just_evaluated and self.result:
            self.tokens = [self.result]
            self.just_evaluated = False
        if not self.tokens or not self._is_number_token(self.tokens[-1]):
            return
        token = self.tokens[-1]
        if token.startswith("-"):
            self.tokens[-1] = token[1:] or "0"
        elif token not in {"0", "0."}:
            self.tokens[-1] = f"-{token}"

    def backspace(self) -> None:
        if self.error:
            self.clear()
            return
        if self.just_evaluated or not self.tokens:
            return
        last = self.tokens[-1]
        if self._is_number_token(last) and len(last) > 1:
            self.tokens[-1] = last[:-1]
            if self.tokens[-1] in {"", "-"}:
                self.tokens.pop()
            return
        self.tokens.pop()

    def clear(self) -> None:
        self.tokens = []
        self.result = ""
        self.error = False
        self.just_evaluated = False

    def equals(self) -> None:
        if self.error or not self.tokens:
            return
        try:
            value = evaluate_expression(self.compile(), self.degrees)
            self.result = format_float(value)
        except (ValueError, ZeroDivisionError, OverflowError, ArithmeticError):
            self._fail()
            return
        self.error = False
        self.just_evaluated = True

    def compile(self) -> str:
        pieces: list[str] = []
        previous: str | None = None
        for token in self.tokens:
            if previous is not None and self._needs_multiply(previous, token):
                pieces.append("*")
            pieces.append(_RENDER.get(token, token))
            previous = token
        text = "".join(pieces)
        missing = text.count("(") - text.count(")")
        if missing < 0:
            raise ValueError("extra )")
        if missing:
            text += ")" * missing
        return text

    def expression_text(self) -> str:
        if not self.tokens and not self.just_evaluated:
            return ""
        pretty = self._pretty()
        if self.just_evaluated:
            unclosed = self._unclosed_parens()
            if unclosed:
                pretty += ")" * unclosed
            return f"{pretty} ="
        return pretty

    def _unclosed_parens(self) -> int:
        opens = 0
        for token in self.tokens:
            if token in _FUNCTIONS or token in {"exp10", "lparen"}:
                opens += 1
            elif token == "rparen":
                opens = max(0, opens - 1)
        return opens

    def display_text(self) -> str:
        if self.error:
            return "Error"
        if self.just_evaluated:
            return self.result
        if not self.tokens:
            return "0"
        last = self.tokens[-1]
        if self._is_number_token(last):
            return last
        if last == "pi":
            return "π"
        if last == "e":
            return "e"
        return "0"

    def _pretty(self) -> str:
        return "".join(_PRETTY.get(token, token) for token in self.tokens)

    def _needs_multiply(self, previous: str, token: str) -> bool:
        if self._is_number_token(previous) and (self._is_number_token(token) or token == "."):
            return False
        previous_ends = self._is_number_token(previous) or previous in _VALUE_ENDERS
        next_starts = self._is_number_token(token) or token in _VALUE_STARTERS
        return previous_ends and next_starts

    def _is_number_token(self, token: str) -> bool:
        return _NUMBER_RE.fullmatch(token) is not None

    def _fail(self) -> None:
        self.error = True
        self.result = ""
        self.just_evaluated = False


class CalculatorWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.engine = CalculatorEngine()
        self.sci_engine = ScientificEngine()
        self.scientific = False
        self.angle_button: QPushButton | None = None
        self.setObjectName("calculator")
        self.setWindowTitle("Calculator")
        self._build_ui()
        self._apply_mode_size(move_window=False)
        self._refresh()

    def _build_ui(self) -> None:
        self.mode_button = QPushButton("Scientific")
        self.mode_button.setProperty("role", "mode")
        self.mode_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_button.setFixedSize(118, 32)
        self.mode_button.clicked.connect(lambda: self._handle("expand"))

        self.expression = QLabel("")
        self.expression.setObjectName("expression")
        self.expression.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.display = QLineEdit("0")
        self.display.setObjectName("display")
        self.display.setReadOnly(True)
        self.display.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.display.setAlignment(Qt.AlignmentFlag.AlignRight)
        display_font = QFont("Segoe UI", 36)
        display_font.setWeight(QFont.Weight.Light)
        self.display.setFont(display_font)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(self.mode_button)
        header.addWidget(self.expression, 1)

        self.sci_panel = QWidget()
        sci_grid = QGridLayout(self.sci_panel)
        sci_grid.setSpacing(8)
        sci_grid.setContentsMargins(0, 0, 12, 0)
        for row, buttons in enumerate(self._science_rows()):
            for column, (label, action) in enumerate(buttons):
                button = self._make_button(label, "science", action)
                button.setFixedSize(74, 64)
                if action == "angle":
                    self.angle_button = button
                sci_grid.addWidget(button, row, column)
        self.sci_panel.setVisible(False)

        basic_grid = QGridLayout()
        basic_grid.setSpacing(10)
        for row, buttons in enumerate(self._basic_rows()):
            column = 0
            for label, role, action in buttons:
                button = self._make_button(label, role, action)
                button.setFixedHeight(64)
                span = 2 if label == "0" else 1
                basic_grid.addWidget(button, row, column, 1, span)
                column += span

        pads = QHBoxLayout()
        pads.setSpacing(0)
        pads.addWidget(self.sci_panel)
        pads.addLayout(basic_grid)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.display)
        layout.addStretch(1)
        layout.addLayout(pads)

        self.setStyleSheet(
            """
            QWidget#calculator { background: #1c1c1e; }
            QLabel#expression {
                color: #a1a1a6;
                font-size: 16px;
                min-height: 32px;
                padding-right: 8px;
            }
            QLineEdit#display {
                background: transparent;
                border: none;
                color: #f5f5f7;
                padding: 0 8px 8px 8px;
                min-height: 72px;
            }
            QPushButton {
                border: none;
                border-radius: 32px;
                font-family: "Segoe UI";
                font-size: 22px;
            }
            QPushButton[role="digit"] { background: #2c2c2e; color: white; }
            QPushButton[role="digit"]:hover { background: #3a3a3c; }
            QPushButton[role="digit"]:pressed { background: #5a5a5e; }
            QPushButton[role="function"] { background: #636366; color: white; }
            QPushButton[role="function"]:hover { background: #7c7c80; }
            QPushButton[role="function"]:pressed { background: #a1a1a6; }
            QPushButton[role="operator"],
            QPushButton[role="equals"] { background: #ff9f0a; color: white; }
            QPushButton[role="operator"]:hover,
            QPushButton[role="equals"]:hover { background: #ffb340; }
            QPushButton[role="operator"]:pressed,
            QPushButton[role="equals"]:pressed { background: #cc7f08; }
            QPushButton[role="science"] {
                background: #2c2c2e;
                color: white;
                font-size: 15px;
                border-radius: 32px;
            }
            QPushButton[role="science"]:hover { background: #3a3a3c; }
            QPushButton[role="science"]:pressed { background: #5a5a5e; }
            QPushButton[role="mode"] {
                background: #2c2c2e;
                color: #ff9f0a;
                font-size: 13px;
                font-weight: 600;
                border-radius: 16px;
            }
            QPushButton[role="mode"]:hover { background: #3a3a3c; }
            QPushButton[role="mode"]:pressed { background: #5a5a5e; }
            """
        )

    def _make_button(self, label: str, role: str, action: str) -> QPushButton:
        button = QPushButton(label)
        button.setProperty("role", role)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, act=action: self._handle(act))
        return button

    def _basic_rows(self) -> list[list[tuple[str, str, str]]]:
        return [
            [("C", "function", "clear"), ("±", "function", "sign"), ("%", "function", "percent"), ("÷", "operator", "/")],
            [("7", "digit", "7"), ("8", "digit", "8"), ("9", "digit", "9"), ("×", "operator", "*")],
            [("4", "digit", "4"), ("5", "digit", "5"), ("6", "digit", "6"), ("−", "operator", "-")],
            [("1", "digit", "1"), ("2", "digit", "2"), ("3", "digit", "3"), ("+", "operator", "+")],
            [("0", "digit", "0"), (".", "digit", "."), ("=", "equals", "=")],
        ]

    def _science_rows(self) -> list[list[tuple[str, str]]]:
        return [
            [("sin", "sin"), ("cos", "cos"), ("tan", "tan"), ("Deg", "angle")],
            [("sin⁻¹", "asin"), ("cos⁻¹", "acos"), ("tan⁻¹", "atan"), ("ln", "ln")],
            [("log", "log"), ("√", "sqrt"), ("x²", "square"), ("xʸ", "power")],
            [("n!", "fact"), ("1/x", "recip"), ("π", "pi"), ("e", "e")],
            [("(", "lparen"), (")", "rparen"), ("|x|", "abs"), ("10ˣ", "exp10")],
        ]

    def _handle(self, action: str) -> None:
        if action == "expand":
            self._toggle_scientific()
            return
        if action == "angle":
            self._toggle_angle()
            return
        if self.scientific:
            self._handle_scientific(action)
        else:
            self._handle_basic(action)
        self._refresh()

    def _handle_basic(self, action: str) -> None:
        engine = self.engine
        if action == "clear":
            engine.clear()
        elif action == "sign":
            engine.toggle_sign()
        elif action == "percent":
            engine.percent()
        elif action == ".":
            engine.input_decimal()
        elif action == "=":
            engine.equals()
        elif action in {"+", "-", "*", "/"}:
            engine.input_operator(action)
        elif action.isdigit():
            engine.input_digit(action)

    def _handle_scientific(self, action: str) -> None:
        engine = self.sci_engine
        functions = {"sin", "cos", "tan", "asin", "acos", "atan", "ln", "log", "sqrt", "abs"}
        if action == "clear":
            engine.clear()
        elif action == "sign":
            engine.toggle_sign()
        elif action == "percent":
            engine.percent()
        elif action == ".":
            engine.input_decimal()
        elif action == "=":
            engine.equals()
        elif action in {"+", "-", "*", "/"}:
            engine.input_operator(action)
        elif action in functions:
            engine.input_function(action)
        elif action in {"square", "fact", "recip"}:
            engine.input_postfix(action)
        elif action == "power":
            engine.input_operator("power")
        elif action in {"pi", "e"}:
            engine.input_constant(action)
        elif action in {"lparen", "rparen"}:
            engine.input_paren(action)
        elif action == "exp10":
            engine.input_function("exp10")
        elif action.isdigit():
            engine.input_digit(action)

    def _toggle_scientific(self) -> None:
        if self.scientific:
            self._collapse()
        else:
            self._expand()
        self._refresh()

    def _expand(self) -> None:
        text = self.engine.display_text()
        self.sci_engine.clear()
        if text not in {"0", "Error"}:
            self.sci_engine.tokens = [text]
            self.sci_engine.result = text
            self.sci_engine.just_evaluated = True
        self.scientific = True
        self.sci_panel.setVisible(True)
        self.mode_button.setText("Basic")
        self.setWindowTitle("Calculator — Scientific")
        self._apply_mode_size(move_window=True)

    def _collapse(self) -> None:
        text = self.sci_engine.display_text()
        self.engine.clear()
        if text not in {"Error", "π", "e"}:
            self.engine.current = text
            self.engine.fresh = True
        elif text == "π":
            self.engine.current = format_float(math.pi)
            self.engine.fresh = True
        elif text == "e":
            self.engine.current = format_float(math.e)
            self.engine.fresh = True
        self.scientific = False
        self.sci_panel.setVisible(False)
        self.mode_button.setText("Scientific")
        self.setWindowTitle("Calculator")
        self._apply_mode_size(move_window=True)

    def _apply_mode_size(self, move_window: bool) -> None:
        width = EXPANDED_WIDTH if self.scientific else NORMAL_WIDTH
        if move_window and self.isVisible():
            delta = EXPANDED_WIDTH - NORMAL_WIDTH
            if self.scientific:
                self.setFixedSize(width, WINDOW_HEIGHT)
                self.move(self.x() - delta, self.y())
            else:
                self.move(self.x() + delta, self.y())
                self.setFixedSize(width, WINDOW_HEIGHT)
            return
        self.setFixedSize(width, WINDOW_HEIGHT)

    def _toggle_angle(self) -> None:
        self.sci_engine.degrees = not self.sci_engine.degrees
        if self.angle_button is not None:
            self.angle_button.setText("Deg" if self.sci_engine.degrees else "Rad")
        if self.sci_engine.just_evaluated and self.sci_engine.tokens:
            self.sci_engine.just_evaluated = False
            self.sci_engine.equals()
        self._refresh()

    def _refresh(self) -> None:
        if self.scientific:
            expression = self.sci_engine.expression_text()
            display = self.sci_engine.display_text()
            angle = "DEG" if self.sci_engine.degrees else "RAD"
            expression = f"{angle}    {expression}".rstrip()
        else:
            expression = self.engine.expression_text()
            display = self.engine.display_text()
        self.expression.setText(expression)
        self.display.setText(display)
        size = 36 if len(display) <= 12 else 24 if len(display) <= 18 else 16
        font = self.display.font()
        font.setPointSize(size)
        self.display.setFont(font)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        text = event.text()
        key = event.key()
        if text.isdigit():
            self._handle(text)
        elif text == ".":
            self._handle(".")
        elif text in {"+", "-", "*", "/"}:
            self._handle(text)
        elif text == "%":
            self._handle("percent")
        elif self.scientific and text == "(":
            self._handle("lparen")
        elif self.scientific and text == ")":
            self._handle("rparen")
        elif self.scientific and text == "^":
            self._handle("power")
        elif self.scientific and text == "!":
            self._handle("fact")
        elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Equal}:
            self._handle("=")
        elif key == Qt.Key.Key_Backspace:
            if self.scientific:
                self.sci_engine.backspace()
            else:
                self.engine.backspace()
            self._refresh()
        elif key in {Qt.Key.Key_Escape, Qt.Key.Key_Delete}:
            self._handle("clear")
        else:
            super().keyPressEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 12))
    window = CalculatorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
