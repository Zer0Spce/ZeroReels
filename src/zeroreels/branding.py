from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _asset_icon_path() -> Path | None:
    roots = []
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        roots.append(Path(bundle))
    roots.extend([Path(__file__).resolve().parents[2], Path.cwd()])
    for root in roots:
        for candidate in (root / "assets" / "zeroreels.ico", root / "zeroreels.ico"):
            if candidate.exists():
                return candidate
    return None


def _draw_icon(size: int = 256) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    dark = QColor("#0D131A")
    mint = QColor("#63E6BE")
    white = QColor("#F4F7FA")

    tile = QRectF(8, 8, size - 16, size - 16)
    p.setPen(QPen(mint, max(3, size * 0.035)))
    p.setBrush(dark)
    p.drawRoundedRect(tile, size * 0.18, size * 0.18)

    # Film-reel circle.
    reel = QRectF(size * 0.17, size * 0.19, size * 0.46, size * 0.46)
    p.setPen(QPen(mint, size * 0.045))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(reel)
    center = QPointF(reel.center())
    hole_r = size * 0.052
    for dx, dy in ((-0.10, -0.10), (0.10, -0.10), (-0.10, 0.10), (0.10, 0.10)):
        c = QPointF(center.x() + size * dx, center.y() + size * dy)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mint)
        p.drawEllipse(c, hole_r, hole_r)

    # Play triangle gives the mark a clear video identity.
    play = QPainterPath()
    play.moveTo(size * 0.39, size * 0.31)
    play.lineTo(size * 0.39, size * 0.53)
    play.lineTo(size * 0.56, size * 0.42)
    play.closeSubpath()
    p.setBrush(white)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(play)

    # Minimal ZR monogram under the reel.
    p.setPen(QPen(white, size * 0.045, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(QPointF(size * 0.22, size * 0.74), QPointF(size * 0.43, size * 0.74))
    p.drawLine(QPointF(size * 0.43, size * 0.74), QPointF(size * 0.22, size * 0.88))
    p.drawLine(QPointF(size * 0.22, size * 0.88), QPointF(size * 0.43, size * 0.88))

    p.setPen(QPen(mint, size * 0.045, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(QPointF(size * 0.56, size * 0.74), QPointF(size * 0.56, size * 0.88))
    p.drawLine(QPointF(size * 0.56, size * 0.74), QPointF(size * 0.70, size * 0.74))
    p.drawArc(QRectF(size * 0.58, size * 0.735, size * 0.17, size * 0.09), -90 * 16, 180 * 16)
    p.drawLine(QPointF(size * 0.66, size * 0.82), QPointF(size * 0.75, size * 0.89))

    p.end()
    return pix


def app_icon() -> QIcon:
    asset = _asset_icon_path()
    if asset:
        icon = QIcon(str(asset))
        if not icon.isNull():
            return icon
    return QIcon(_draw_icon())
