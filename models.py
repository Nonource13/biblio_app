# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False) # Hash
    role = db.Column(db.String(50), nullable=False) # 'membre', 'bibliothecaire', ...
    email = db.Column(db.String(120), unique=True, nullable=True) # Ajout email (optionnel mais recommandé)

    # --- AJOUT : Champs Abonnement (pour rôle 'membre') ---
    subscription_status = db.Column(db.String(20), default='inactive', nullable=False) # inactive, active, pending, expired
    subscription_type = db.Column(db.String(20), nullable=True) # monthly, annual, none
    subscription_start_date = db.Column(db.DateTime, nullable=True)
    subscription_end_date = db.Column(db.DateTime, nullable=True)
    # ----------------------------------------------------

    # Relations
    reservations = db.relationship('Reservation', backref='user', lazy=True, cascade="all, delete-orphan")
    loans = db.relationship('Loan', backref='user', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        sub_info = ""
        if self.role == 'membre':
            sub_info = f" Sub:{self.subscription_status}"
            if self.subscription_end_date:
                 sub_info += f" until {self.subscription_end_date.strftime('%Y-%m-%d')}"
        return f'<User {self.username} ({self.role}){sub_info}>'


class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(150), nullable=True)
    summary = db.Column(db.Text, nullable=True)
    # Statut principal (souvent lié à la disponibilité physique)
    status = db.Column(db.String(50), nullable=False, default='disponible') # 'disponible', 'emprunte'

    # --- Indicateurs de format ---
    is_physical = db.Column(db.Boolean, default=True, nullable=False)
    is_digital = db.Column(db.Boolean, default=False, nullable=False)
    # Chemin relatif du fichier PDF (seulement si is_digital est True)
    file_path = db.Column(db.String(300), nullable=True)
    # -----------------------------

    # --- AJOUT : Champ pour l'image de couverture ---
    # Stocke le nom du fichier image (ex: 'uuid_couverture.jpg')
    cover_image_filename = db.Column(db.String(100), nullable=True)
    # ----------------------------------------------
   
    # Relations
    reservations = db.relationship('Reservation', backref='document', lazy=True, cascade="all, delete-orphan")
    loans = db.relationship('Loan', backref='document', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        formats = []
        if self.is_physical: formats.append("Physique")
        if self.is_digital: formats.append("Numérique")
        img_status = " (avec image)" if self.cover_image_filename else ""
        return f'<Document {self.id}: {self.title}{img_status} ({", ".join(formats)})>'

# Modèle Reservation (pour le physique)
class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    reservation_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Statut: 'active', 'cancelled', 'honored'
    status = db.Column(db.String(50), nullable=False, default='active')

    # backrefs définis dans User et Document

    def __repr__(self):
        return f'<Reservation ID {self.id} - User {self.user_id} Doc {self.document_id} ({self.status})>'

# Modèle Loan (pour le numérique)
class Loan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    loan_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=False)
    # Statut: 'active', 'returned', 'expired'
    status = db.Column(db.String(50), nullable=False, default='active')

    # backrefs définis dans User et Document

    def __repr__(self):
        return f'<Loan ID {self.id} - User {self.user_id} Doc {self.document_id} Due: {self.due_date} ({self.status})>'