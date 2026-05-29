"""
QR code generator for payment details.

Generates stylized QR codes with:
- Embedded logo/icon (optional)
- Custom colors
- High error correction for reliability
- Multiple output formats (PNG bytes, file_id)
"""

import io
from typing import Optional
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.colormasks import SolidFillColorMask
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
from PIL import Image, ImageDraw, ImageFont
from loguru import logger


class QRGenerator:

    @staticmethod
    def generate(
        data: str,
        title: Optional[str] = None,
        amount: Optional[float] = None,
        fill_color: str = "#1a1a2e",
        back_color: str = "#ffffff",
        logo_path: Optional[str] = None,
        box_size: int = 10,
        border: int = 4,
    ) -> bytes:
        """
        Generate QR code as PNG bytes.

        Args:
            data: QR content (payment details, URL, etc.)
            title: Optional label below QR
            amount: Optional amount to show
            fill_color: Dark module color (hex)
            back_color: Background color (hex)
            logo_path: Optional path to logo image to embed
            box_size: Size of each QR module
            border: Border size
        """
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=box_size,
            border=border,
        )
        qr.add_data(data)
        qr.make(fit=True)

        fill_rgb = _hex_to_rgb(fill_color)
        back_rgb = _hex_to_rgb(back_color)

        try:
            img = qr.make_image(
                image_factory=StyledPilImage,
                module_drawer=RoundedModuleDrawer(),
                color_mask=SolidFillColorMask(
                    front_color=fill_rgb,
                    back_color=back_rgb,
                ),
            ).convert("RGBA")
        except Exception:
            img = qr.make_image(fill_color=fill_color, back_color=back_color).convert("RGBA")

        if logo_path:
            try:
                img = _embed_logo(img, logo_path)
            except Exception as e:
                logger.warning(f"QR logo embed failed: {e}")

        if title or amount is not None:
            img = _add_caption(img, title, amount, back_rgb)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @staticmethod
    def generate_payment_qr(
        payment_details: str,
        group_title: str,
        tariff_name: str,
        amount: float,
        currency: str = "RUB",
    ) -> bytes:
        """Convenience method for payment QR codes."""
        caption = f"{group_title} · {tariff_name}"
        lines = [payment_details]
        if amount > 0:
            lines.append(f"Сумма: {int(amount)} {currency}")
        content = "\n".join(lines)
        return QRGenerator.generate(
            data=content,
            title=caption,
            amount=amount if amount > 0 else None,
        )

    @staticmethod
    def validate_qr_bytes(data: bytes) -> bool:
        """Validate that bytes are a valid PNG image."""
        if len(data) < 8:
            return False
        return data[:8] == b"\x89PNG\r\n\x1a\n"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _embed_logo(img: Image.Image, logo_path: str) -> Image.Image:
    logo = Image.open(logo_path).convert("RGBA")
    qr_size = img.size[0]
    logo_size = qr_size // 5
    logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
    pos = ((qr_size - logo_size) // 2, (qr_size - logo_size) // 2)
    bg = Image.new("RGBA", img.size, (255, 255, 255, 0))
    bg.paste(img, (0, 0))
    bg.paste(logo, pos, logo)
    return bg


def _add_caption(
    img: Image.Image,
    title: Optional[str],
    amount: Optional[float],
    back_rgb: tuple,
) -> Image.Image:
    padding = 20
    line_h = 30
    extra_lines = 0
    if title:
        extra_lines += 1
    if amount is not None:
        extra_lines += 1

    if extra_lines == 0:
        return img

    new_h = img.height + padding * 2 + line_h * extra_lines
    new_img = Image.new("RGBA", (img.width, new_h), (*back_rgb, 255))
    new_img.paste(img, (0, 0))

    draw = ImageDraw.Draw(new_img)
    y = img.height + padding

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
        font_sm = font

    if title:
        w = draw.textlength(title, font=font_sm) if hasattr(draw, "textlength") else 0
        x = max(0, (img.width - w) // 2) if w > 0 else 10
        draw.text((x, y), title, fill=(30, 30, 30, 255), font=font_sm)
        y += line_h

    if amount is not None:
        amt_text = f"{int(amount)} ₽"
        w = draw.textlength(amt_text, font=font) if hasattr(draw, "textlength") else 0
        x = max(0, (img.width - w) // 2) if w > 0 else 10
        draw.text((x, y), amt_text, fill=(20, 100, 20, 255), font=font)

    return new_img
