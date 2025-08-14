# app.py (Version Corrigée Complète)
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, abort, jsonify
from models import db, User, Document, Reservation, Loan
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename # Pour sécuriser les noms de fichiers uploadés
from werkzeug.security import generate_password_hash, check_password_hash
import uuid # Pour générer des noms de fichiers uniques
from sqlalchemy import or_
from sqlalchemy import func
import openai 
from dotenv import load_dotenv
from waitress import serve
load_dotenv()

# Configuration de l'application Flask
app = Flask(__name__)

# Configuration de la base de données SQLite
basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
os.makedirs(instance_path, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(instance_path, 'library.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'une-cle-secrete-tres-difficile-a-deviner' # À CHANGER EN PRODUCTION

# Configuration PDF
PDF_UPLOAD_FOLDER = os.path.join(app.instance_path, 'uploads', 'pdfs')
os.makedirs(PDF_UPLOAD_FOLDER, exist_ok=True)
DIGITAL_LOAN_DURATION = 14 # jours

# Configuration Images Couverture
COVER_UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads', 'covers')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
os.makedirs(COVER_UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    """Vérifie si l'extension du fichier est autorisée."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Configuration Clé API OpenAI ---
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    print("\n" + "*"*40)
    print("ATTENTION : Clé API OpenAI (OPENAI_API_KEY) non trouvée dans l'environnement.")
    print("Le chatbot IA ne pourra pas fonctionner.")
    print("Veuillez créer un fichier .env et y ajouter OPENAI_API_KEY=votre_clé")
    print("*"*40 + "\n")
    # On assigne None pour pouvoir vérifier plus tard
    openai.api_key = None
else:
    openai.api_key = openai_api_key
    print("Clé API OpenAI chargée avec succès.")

# Initialisation de SQLAlchemy
db.init_app(app)

# --- Context Processor pour injecter current_user dans les templates ---
@app.context_processor
def inject_user():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        return dict(current_user=user)
    return dict(current_user=None)
# -----------------------------------------------------------------------

# --- Routes de Base ---
@app.route('/')
def index():
    return render_template('index.html')
@app.route('/')
def home():
    return "Hello, Bibliosmart!"

if __name__ == "__main__":
    serve(app, host="127.0.0.1", port=5000)

    
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            flash('Nom d\'utilisateur et mot de passe requis.', 'warning')
            return redirect(url_for('login'))
        user = User.query.filter_by(username=username).first()
        # !! RAPPEL SECURITE MDP !! - Utiliser le hachage en production
        if user and check_password_hash(user.password, password): # <-- MODIFIÉ ICI
            session['user_id'] = user.id
            session['user_role'] = user.role
            session['username'] = user.username
            flash('Connexion réussie !', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Nom d\'utilisateur ou mot de passe incorrect.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')
# --- FIN MODIFICATION /login ---

@app.route('/logout')
def logout():
    session.clear() # Efface toutes les données de la session
    flash('Vous avez été déconnecté.', 'info')
    return redirect(url_for('index'))
# --- Fin Routes de Base ---


# --- Route Tableau de Bord Principal ---
@app.route('/dashboard')
def dashboard():
    if 'user_role' not in session:
        flash('Veuillez vous connecter.', 'warning')
        return redirect(url_for('login'))

    role = session['user_role']
    user_id = session['user_id']

    if role == 'membre':
        user_loans = []; user_reservations = []
        try:
            user_loans = Loan.query.filter_by(user_id=user_id, status='active').order_by(Loan.due_date).all()
            user_reservations = Reservation.query.filter_by(user_id=user_id, status='active').order_by(Reservation.reservation_date.desc()).all()
        except Exception as e: flash(f"Erreur récupération données: {e}", "danger")
        today_date = datetime.utcnow().date()
        return render_template('member_dashboard.html', loans=user_loans, reservations=user_reservations, today_date=today_date)

    elif role == 'bibliothecaire':
        return render_template('librarian_dashboard.html')
    elif role == 'prepose':
        return render_template('attendant_dashboard.html')

    elif role == 'gerant':
        # --- Calcul des statistiques pour le rapport ---
        report_stats = {}
        try:
            report_stats['total_documents'] = db.session.query(func.count(Document.id)).scalar()
            report_stats['physical_available'] = Document.query.filter_by(is_physical=True, status='disponible').count()
            report_stats['physical_borrowed'] = Document.query.filter_by(is_physical=True, status='emprunte').count()
            report_stats['digital_documents'] = Document.query.filter_by(is_digital=True).count()
            report_stats['active_digital_loans'] = Loan.query.filter_by(status='active').count()
            report_stats['active_reservations'] = Reservation.query.filter_by(status='active').count()
            report_stats['total_members'] = User.query.filter_by(role='membre').count()
            report_stats['active_members'] = User.query.filter_by(role='membre', subscription_status='active').count() # Si abo implémenté
            report_stats['total_staff'] = User.query.filter(User.role.in_(['bibliothecaire', 'prepose', 'gerant'])).count()

            # Optionnel: Documents les plus empruntés (numérique) - Exemple simple
            most_loaned_query = db.session.query(
                    Document.title, func.count(Loan.id).label('loan_count')
                ).join(Loan).filter(Loan.status == 'active') \
                 .group_by(Document.id).order_by(func.count(Loan.id).desc()).limit(5).all()
            report_stats['most_loaned_digital'] = most_loaned_query

        except Exception as e:
            flash(f"Erreur lors du calcul des statistiques : {e}", "danger")
            print(f"Erreur DB calcul stats gérant: {e}")
            report_stats = {} # Renvoyer vide en cas d'erreur

        # --- Récupération des listes d'utilisateurs ---
        librarians = []
        members = []
        try:
            librarians = User.query.filter_by(role='bibliothecaire').order_by(User.username).all()
            members = User.query.filter_by(role='membre').order_by(User.username).all()
        except Exception as e:
            flash(f"Erreur lors de la récupération des listes d'utilisateurs : {e}", "danger")
            print(f"Erreur DB listes utilisateurs gérant: {e}")


        return render_template('manager_dashboard.html',
                               stats=report_stats,
                               librarians=librarians,
                               members=members)
    else:
        flash('Rôle utilisateur non reconnu.', 'danger')
        return redirect(url_for('logout'))
# --- FIN MISE À JOUR Route /dashboard ---


# --- Routes Catalogue & Détail ---
@app.route('/catalogue')
def catalogue():
    if 'user_id' not in session:
        flash('Connectez-vous pour voir le catalogue.', 'warning')
        return redirect(url_for('login'))

    search_query = request.args.get('q', None)
    try:
        query_builder = Document.query
        if search_query:
            search_term = f"%{search_query}%"
            query_builder = query_builder.filter(
                or_(
                    Document.title.ilike(search_term),
                    Document.author.ilike(search_term)
                    # Ajouter Document.summary.ilike(search_term) si besoin
                )
            )
            print(f"Recherche catalogue pour: {search_query}") # Log serveur
        all_documents = query_builder.order_by(Document.title).all()
    except Exception as e:
        flash(f"Erreur lors de la récupération du catalogue: {e}", "danger")
        print(f"Erreur DB catalogue: {e}") # Log serveur
        all_documents = []
    return render_template('catalogue.html', documents=all_documents)

@app.route('/document/<int:doc_id>')
def document_detail(doc_id):
    if 'user_id' not in session:
        flash('Connectez-vous pour voir les détails.', 'warning')
        return redirect(url_for('login'))
    try:
        document = Document.query.get_or_404(doc_id)
    except Exception as e:
        flash(f"Erreur lors de la récupération du document: {e}", "danger")
        print(f"Erreur DB détail doc {doc_id}: {e}") # Log serveur
        return redirect(url_for('catalogue'))
    return render_template('document_detail.html', doc=document)
# --- Fin Routes Catalogue & Détail ---


# --- Route Ajout Document (Bibliothécaire) ---
@app.route('/add_document', methods=['POST'])
def add_document():
    if session.get('user_role') != 'bibliothecaire':
        flash("Accès non autorisé.", "danger"); return redirect(url_for('dashboard'))

    # Récupération champs
    title = request.form.get('title'); author = request.form.get('author'); summary = request.form.get('summary')
    is_physical = request.form.get('is_physical') == 'y'; is_digital = request.form.get('is_digital') == 'y'
    file_path_pdf = request.form.get('file_path', None); cover_image_file = request.files.get('cover_image')
    cover_filename_to_save = None

    # Validations initiales
    if not title: flash("Titre requis.", "warning"); return redirect(url_for('dashboard'))
    if not is_physical and not is_digital: flash("Format requis.", "warning"); return redirect(url_for('dashboard'))
    if is_digital and (not file_path_pdf or not file_path_pdf.strip()): flash("Nom fichier PDF requis si Numérique coché.", "warning"); return redirect(url_for('dashboard'))

    # Traitement Image
    if cover_image_file and cover_image_file.filename != '':
        if allowed_file(cover_image_file.filename):
            original_filename = secure_filename(cover_image_file.filename)
            try:
                extension = original_filename.rsplit('.', 1)[1].lower()
                unique_filename = f"{uuid.uuid4().hex}.{extension}"
                save_path = os.path.join(COVER_UPLOAD_FOLDER, unique_filename)
                try:
                    cover_image_file.save(save_path)
                    cover_filename_to_save = unique_filename
                    print(f"Image uploadée sauvegardée: {unique_filename}")
                except Exception as e:
                    flash(f"Erreur sauvegarde image: {e}", "danger"); print(f"Erreur save img: {e}")
            except IndexError:
                 flash(f"Nom de fichier image invalide: {original_filename}", "warning")
        else:
            flash("Format image non autorisé.", "warning")

    # Traitement Chemin PDF
    cleaned_file_path_pdf = None
    if is_digital and file_path_pdf:
        cleaned_file_path_pdf = os.path.basename(file_path_pdf.strip())
        if not cleaned_file_path_pdf:
            flash("Nom fichier PDF invalide.", "warning"); return redirect(url_for('dashboard'))
        # Optionnel : Vérifier existence fichier PDF
        # full_path_pdf = os.path.join(PDF_UPLOAD_FOLDER, cleaned_file_path_pdf)
        # if not os.path.exists(full_path_pdf):
        #    flash(f"Fichier PDF '{cleaned_file_path_pdf}' non trouvé sur le serveur.", "danger")
        #    return redirect(url_for('dashboard'))

    # Création et sauvegarde en DB
    try:
        new_doc = Document(
            title=title, author=author or None, summary=summary or None, status='disponible',
            is_physical=is_physical, is_digital=is_digital, file_path=cleaned_file_path_pdf if is_digital else None,
            cover_image_filename=cover_filename_to_save
        )
        db.session.add(new_doc); db.session.commit()
        formats = [f for f, present in [("Physique", is_physical), ("Numérique", is_digital)] if present]
        img_msg = " avec image" if cover_filename_to_save else ""
        flash(f"Document '{title}' ({', '.join(formats)}) ajouté{img_msg}.", "success")
    except Exception as e:
        db.session.rollback(); flash(f"Erreur ajout en base de données: {e}", "danger"); print(f"Erreur DB ajout: {e}")

    return redirect(url_for('dashboard'))
# --- Fin Route Ajout Document ---


# --- Route Édition Document (Bibliothécaire) ---
@app.route('/edit_document/<int:doc_id>', methods=['GET', 'POST'])
def edit_document(doc_id):
    if session.get('user_role') != 'bibliothecaire':
        flash("Accès non autorisé.", "danger"); return redirect(url_for('index'))

    doc = Document.query.get_or_404(doc_id)
    old_cover_filename = doc.cover_image_filename
    old_pdf_filename = doc.file_path
    original_physical_status = doc.status if doc.is_physical else None

    if request.method == 'POST':
        # Récupération données
        doc.title = request.form.get('title')
        doc.author = request.form.get('author')
        doc.summary = request.form.get('summary')
        doc.is_physical = request.form.get('is_physical') == 'y'
        doc.is_digital = request.form.get('is_digital') == 'y'
        new_file_path_pdf = request.form.get('file_path', None)
        remove_cover = request.form.get('remove_cover') == 'y'
        new_cover_image_file = request.files.get('cover_image')
        new_physical_status = request.form.get('status')

        # Validations
        if not doc.title: flash("Titre requis.", "warning"); return render_template('edit_document.html', doc=doc)
        if not doc.is_physical and not doc.is_digital: flash("Format requis.", "warning"); return render_template('edit_document.html', doc=doc)
        if doc.is_digital and (not new_file_path_pdf or not new_file_path_pdf.strip()): flash("Nom fichier PDF requis.", "warning"); return render_template('edit_document.html', doc=doc)
        if doc.is_physical and new_physical_status and new_physical_status not in ['disponible', 'emprunte']:
            flash("Statut physique invalide.", "warning"); return render_template('edit_document.html', doc=doc)

        # Traitement PDF Path
        cleaned_new_pdf_path = None
        if doc.is_digital and new_file_path_pdf:
            cleaned_new_pdf_path = os.path.basename(new_file_path_pdf.strip())
            if not cleaned_new_pdf_path: flash("Nom fichier PDF invalide.", "warning"); return render_template('edit_document.html', doc=doc)
            doc.file_path = cleaned_new_pdf_path
        elif not doc.is_digital:
            doc.file_path = None # Supprimer chemin si devient non-numérique

        # Traitement Image Couverture (CORRIGÉ AVEC original_filename)
        delete_old_cover = False
        if remove_cover:
            doc.cover_image_filename = None
            delete_old_cover = True
            print(f"Suppression image demandée pour doc {doc_id}")
        elif new_cover_image_file and new_cover_image_file.filename != '':
            if allowed_file(new_cover_image_file.filename):
                original_filename = secure_filename(new_cover_image_file.filename) # Définition ici
                try:
                    extension = original_filename.rsplit('.', 1)[1].lower()
                    unique_filename = f"{uuid.uuid4().hex}.{extension}"
                    save_path = os.path.join(COVER_UPLOAD_FOLDER, unique_filename)
                    try:
                        new_cover_image_file.save(save_path)
                        doc.cover_image_filename = unique_filename
                        delete_old_cover = True
                        print(f"Nouvelle image sauvegardée: {unique_filename}")
                    except Exception as e:
                        flash(f"Erreur sauvegarde nouvelle image: {e}", "danger"); print(f"Erreur save img: {e}")
                except IndexError:
                     flash(f"Nom de fichier image invalide: {original_filename}", "warning")
            else:
                flash("Format nouvelle image non autorisé.", "warning")

        # Application et Synchro Statut Physique
        reservations_cancelled_count = 0
        if doc.is_physical and new_physical_status:
            if original_physical_status == 'emprunte' and new_physical_status == 'disponible':
                print(f"Statut doc {doc.id} changé: emp -> dispo. Vérif réservations...")
                active_reservations = Reservation.query.filter_by(document_id=doc.id, status='active').all()
                for resa in active_reservations:
                    resa.status = 'cancelled'; reservations_cancelled_count += 1
                    print(f"  > Annulation Résa ID {resa.id}")
            doc.status = new_physical_status # Appliquer le nouveau statut
        elif not doc.is_physical:
            doc.status = 'disponible' # Optionnel : reset si devient non-physique

        # Sauvegarde DB
        try:
            db.session.commit() # Commit modifs sur doc et réservations
            # Suppression ancien fichier image après commit réussi
            if delete_old_cover and old_cover_filename:
                try: os.remove(os.path.join(COVER_UPLOAD_FOLDER, old_cover_filename)); print(f"Ancienne img supprimée: {old_cover_filename}")
                except OSError as e: print(f"Err suppr img {old_cover_filename}: {e}")

            flash_message = f"Document '{doc.title}' modifié."
            if reservations_cancelled_count > 0:
                flash_message += f" {reservations_cancelled_count} réservation(s) annulée(s)."
                flash(flash_message, "warning")
            else: flash(flash_message, "success")
            return redirect(url_for('document_detail', doc_id=doc.id))
        except Exception as e:
            db.session.rollback(); flash(f"Erreur modification DB: {e}", "danger"); print(f"Erreur DB modif: {e}")

    # Méthode GET
    return render_template('edit_document.html', doc=doc)
# --- Fin Route Édition Document ---


# --- Route Suppression Document ---
@app.route('/delete_document/<int:doc_id>', methods=['POST'])
def delete_document(doc_id):
    if session.get('user_role') != 'bibliothecaire': flash("Accès non autorisé.", "danger"); return redirect(url_for('catalogue'))
    doc = Document.query.get_or_404(doc_id); title = doc.title; cover = doc.cover_image_filename; pdf = doc.file_path
    try:
        # Suppression DB (cascade gère prêts/résas)
        db.session.delete(doc); db.session.commit()
        # Suppression fichiers après succès DB
        if cover:
            try: os.remove(os.path.join(COVER_UPLOAD_FOLDER, cover)); print(f"Img supprimée: {cover}")
            except OSError as e: print(f"Err suppr img {cover}: {e}")
        if pdf:
            try: os.remove(os.path.join(PDF_UPLOAD_FOLDER, pdf)); print(f"PDF supprimé: {pdf}")
            except OSError as e: print(f"Err suppr pdf {pdf}: {e}")
        flash(f"Document '{title}' supprimé.", "success")
    except Exception as e:
        db.session.rollback(); flash(f"Erreur suppression: {e}", "danger"); print(f"Erreur DB suppr: {e}")
    return redirect(url_for('catalogue'))
# --- Fin Route Suppression Document ---


# --- Routes Prêt/Retour Physique (Préposé) ---
@app.route('/record_loan', methods=['POST'])
def record_loan():
    if session.get('user_role') != 'prepose': flash("Accès non autorisé.", "danger"); return redirect(url_for('dashboard'))
    doc_id_str = request.form.get('document_id'); member_id = request.form.get('member_id') # Récupérer ID membre aussi
    if not doc_id_str: flash("ID document requis.", "warning"); return redirect(url_for('dashboard'))
    if not member_id: flash("ID membre requis.", "warning"); return redirect(url_for('dashboard')) # Valider membre
    try:
        doc_id = int(doc_id_str)
        doc = Document.query.get(doc_id)
        # Vérifier existence membre (simpliste)
        member = User.query.filter_by(username=member_id, role='membre').first() # Ou rechercher par un ID membre numérique
        if not member: flash(f"Membre ID '{member_id}' non trouvé.", "warning"); return redirect(url_for('dashboard'))

        if doc and doc.is_physical:
            if doc.status == 'disponible':
                doc.status = 'emprunte'; db.session.commit()
                # NOTE: Idéalement, créer un enregistrement de prêt physique ici aussi
                flash(f"Doc '{doc.title}' prêté à {member_id}.", "success")
            else: flash(f"Doc '{doc.title}' non dispo.", "warning")
        elif doc: flash("Pour docs physiques.", "warning")
        else: flash(f"Doc ID {doc_id} non trouvé.", "danger")
    except ValueError: flash("ID invalide.", "danger")
    except Exception as e: db.session.rollback(); flash(f"Erreur prêt: {e}", "danger"); print(f"Err prêt physique: {e}")
    return redirect(url_for('dashboard'))

@app.route('/record_return', methods=['POST'])
def record_return():
    if session.get('user_role') != 'prepose': flash("Accès non autorisé.", "danger"); return redirect(url_for('dashboard'))
    doc_id_str = request.form.get('document_id')
    if not doc_id_str: flash("ID document requis.", "warning"); return redirect(url_for('dashboard'))
    try:
        doc_id = int(doc_id_str)
        doc = Document.query.get(doc_id)
        if doc and doc.is_physical:
            if doc.status == 'emprunte':
                doc.status = 'disponible'; db.session.commit()
                # NOTE: Logique pour notifier la prochaine personne en réservation ici
                flash(f"Doc '{doc.title}' retourné.", "success")
            else: flash(f"Doc '{doc.title}' non emprunté.", "warning")
        elif doc: flash("Pour docs physiques.", "warning")
        else: flash(f"Doc ID {doc_id} non trouvé.", "danger")
    except ValueError: flash("ID invalide.", "danger")
    except Exception as e: db.session.rollback(); flash(f"Erreur retour: {e}", "danger"); print(f"Err retour physique: {e}")
    return redirect(url_for('dashboard'))
# --- Fin Routes Prêt/Retour Physique ---


# --- Routes Actions Membre ---
@app.route('/borrow_digital/<int:doc_id>', methods=['POST'])
def borrow_digital(doc_id):
    if 'user_id' not in session: flash("Connectez-vous.", "warning"); return redirect(url_for('login'))
    if session.get('user_role') != 'membre': flash("Membres seulement.", "danger"); return redirect(url_for('dashboard'))
    user_id = session['user_id']
    try:
        doc = Document.query.get_or_404(doc_id)
        if not doc.is_digital: flash("Pas version numérique.", "warning"); return redirect(url_for('document_detail', doc_id=doc_id))
        if not doc.file_path: flash("Chemin fichier manquant.", "danger"); return redirect(url_for('document_detail', doc_id=doc_id))
        existing_loan = Loan.query.filter_by(user_id=user_id, document_id=doc_id, status='active').first()
        if existing_loan: flash(f"'{doc.title}' déjà emprunté.", "info"); return redirect(url_for('document_detail', doc_id=doc_id))
        full_file_path = os.path.join(PDF_UPLOAD_FOLDER, doc.file_path)
        if not os.path.exists(full_file_path): flash("Fichier serveur manquant.", "danger"); print(f"Err Fichier Manquant: {full_file_path}"); return redirect(url_for('document_detail', doc_id=doc_id))
        loan_date = datetime.utcnow(); due_date = loan_date + timedelta(days=DIGITAL_LOAN_DURATION)
        new_loan = Loan(user_id=user_id, document_id=doc_id, loan_date=loan_date, due_date=due_date, status='active')
        db.session.add(new_loan); db.session.commit()
        flash(f"'{doc.title}' emprunté jusqu'au {due_date.strftime('%d/%m/%Y')}.", "success")
    except Exception as e: db.session.rollback(); flash(f"Erreur emprunt: {e}", "danger"); print(f"Err emprunt num: {e}")
    return redirect(url_for('dashboard'))

@app.route('/reserve_document/<int:doc_id>', methods=['POST'])
def reserve_document(doc_id):
    if 'user_id' not in session: flash("Connectez-vous.", "warning"); return redirect(url_for('login'))
    if session.get('user_role') != 'membre': flash("Membres seulement.", "danger"); return redirect(url_for('dashboard'))
    user_id = session['user_id']
    try:
        doc = Document.query.get_or_404(doc_id)
        if not doc.is_physical: flash("Résa pour docs physiques.", "warning"); return redirect(url_for('document_detail', doc_id=doc_id))
        existing_res = Reservation.query.filter_by(user_id=user_id, document_id=doc_id, status='active').first()
        if existing_res: flash(f"'{doc.title}' déjà réservé.", "info"); return redirect(url_for('document_detail', doc_id=doc_id))
        if doc.status == 'emprunte':
            new_res = Reservation(user_id=user_id, document_id=doc_id); db.session.add(new_res); db.session.commit()
            flash(f"'{doc.title}' réservé.", "success")
        elif doc.status == 'disponible': flash(f"'{doc.title}' est disponible.", "info")
        else: flash(f"'{doc.title}' non réservable ({doc.status}).", "warning")
    except Exception as e: db.session.rollback(); flash(f"Erreur résa: {e}", "danger"); print(f"Err résa physique: {e}")
    return redirect(url_for('document_detail', doc_id=doc_id))

@app.route('/access_document/<int:loan_id>')
def access_document(loan_id):
    if 'user_id' not in session: abort(401)
    user_id = session['user_id']
    try:
        loan = Loan.query.get_or_404(loan_id)
        if loan.user_id != user_id: abort(403)
        if loan.status != 'active': flash("Prêt inactif.", "warning"); return redirect(url_for('dashboard'))
        if datetime.utcnow() > loan.due_date: loan.status = 'expired'; db.session.commit(); flash("Prêt terminé.", "warning"); return redirect(url_for('dashboard'))
        doc = loan.document
        if not doc or not doc.file_path: abort(404)
        file_path_in_db = doc.file_path
        if '..' in file_path_in_db or file_path_in_db.startswith('/'): abort(400)
        return send_from_directory(PDF_UPLOAD_FOLDER, file_path_in_db, as_attachment=False)
    except FileNotFoundError: print(f"ERREUR: Fichier non trouvé! Loan {loan_id}, Path: {file_path_in_db}"); abort(404)
    except Exception as e: flash(f"Erreur accès doc: {e}", "danger"); print(f"Err Accès Doc {loan_id}: {e}"); return redirect(url_for('dashboard'))

@app.route('/return_digital/<int:loan_id>', methods=['POST'])
def return_digital(loan_id):
    if 'user_id' not in session: flash("Connectez-vous.", "warning"); return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        loan = Loan.query.get_or_404(loan_id)
        if loan.user_id != user_id: flash("Action non autorisée.", "danger"); return redirect(url_for('dashboard'))
        if loan.status != 'active': flash("Prêt déjà inactif.", "info"); return redirect(url_for('dashboard'))
        loan.status = 'returned'; db.session.commit()
        flash(f"'{loan.document.title}' retourné.", "success")
    except Exception as e: db.session.rollback(); flash(f"Erreur retour: {e}", "danger"); print(f"Err DB Retour Num: {e}")
    return redirect(url_for('dashboard'))

@app.route('/cancel_reservation/<int:reservation_id>', methods=['POST'])
def cancel_reservation(reservation_id):
    if 'user_id' not in session: flash("Connectez-vous.", "warning"); return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        res = Reservation.query.get_or_404(reservation_id)
        if res.user_id != user_id: flash("Action non autorisée.", "danger"); return redirect(url_for('dashboard'))
        if res.status != 'active': flash("Réservation déjà inactive.", "info"); return redirect(url_for('dashboard'))
        res.status = 'cancelled'; db.session.commit()
        flash(f"Réservation pour '{res.document.title}' annulée.", "success")
    except Exception as e: db.session.rollback(); flash(f"Erreur annulation: {e}", "danger"); print(f"Err DB Annul Résa: {e}")
    return redirect(url_for('dashboard'))

@app.route('/pay_fine_simulated/<int:doc_id>', methods=['POST'])
def pay_fine_simulated(doc_id):
    if 'user_id' not in session: flash("Connectez-vous.", "warning"); return redirect(url_for('login'))
    doc = Document.query.get(doc_id); doc_title = f" (lié à '{doc.title}')" if doc else ""
    flash(f"Paiement amende simulé traité{doc_title}.", "success")
    print(f"--- Sim Pmt Amende --- User: {session['user_id']}, Doc: {doc_id} ---")
    return redirect(url_for('document_detail', doc_id=doc_id))
# --- Fin Routes Actions Membre ---

# app.py
# ... imports (generate_password_hash, check_password_hash, datetime, timedelta) ...

# --- NOUVELLE ROUTE : Inscription Membre ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    # Si l'utilisateur est déjà connecté, le rediriger
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email') # Optionnel
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        subscription_type = request.form.get('subscription_type') # 'monthly' or 'annual'

        # Validations
        if not username or not password or not confirm_password or not subscription_type:
            flash("Tous les champs marqués * sont requis.", "warning")
            return redirect(url_for('register'))
        if len(password) < 6:
             flash("Le mot de passe doit faire au moins 6 caractères.", "warning")
             return redirect(url_for('register'))
        if password != confirm_password:
            flash("Les mots de passe ne correspondent pas.", "warning")
            return redirect(url_for('register'))

        # Vérifier si username ou email existe déjà
        existing_user = User.query.filter(or_(User.username == username, User.email == email if email else False)).first()
        if existing_user:
            flash("Ce nom d'utilisateur ou email est déjà pris.", "warning")
            return redirect(url_for('register'))

        # Hacher le mot de passe
        hashed_password = generate_password_hash(password)

        # Créer l'utilisateur avec statut 'pending'
        try:
            new_user = User(
                username=username,
                password=hashed_password,
                email=email if email else None,
                role='membre',
                subscription_status='pending', # En attente de paiement
                subscription_type=subscription_type
            )
            db.session.add(new_user)
            db.session.commit()
            print(f"Utilisateur {username} créé (ID: {new_user.id}) avec statut pending.")

            # Préparer les détails pour la page de paiement
            plan_details = {
                'monthly': {'name': 'Mensuel', 'price': '5.00'},
                'annual': {'name': 'Annuel', 'price': '50.00'}
            }

            # Rediriger vers la simulation de paiement
            return render_template('simulate_payment.html',
                                   user_id=new_user.id,
                                   username=new_user.username,
                                   subscription_type=subscription_type,
                                   plan_details=plan_details.get(subscription_type, {'name': 'Inconnu', 'price': 'N/A'}))

        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de la création du compte : {e}", "danger")
            print(f"Erreur DB inscription: {e}")
            return redirect(url_for('register'))

    # Méthode GET : afficher le formulaire
    return render_template('register.html')
# --- FIN ROUTE INSCRIPTION ---


# app.py
# ... imports ...

# --- Route Traitement Paiement (Ajustée pour ignorer les détails de carte) ---
@app.route('/process_simulated_payment', methods=['POST'])
def process_simulated_payment():
    # Récupérer UNIQUEMENT les données nécessaires pour l'activation
    user_id = request.form.get('user_id')
    subscription_type = request.form.get('subscription_type')

    # Récupérer les données de carte (pour montrer qu'elles sont reçues, MAIS NE PAS LES UTILISER NI LES STOCKER)
    cardholder_name = request.form.get('cardholder_name')
    card_number = request.form.get('card_number') # NE PAS STOCKER / TRAITER
    expiry_date = request.form.get('expiry_date') # NE PAS STOCKER / TRAITER
    cvc = request.form.get('cvc')             # NE PAS STOCKER / TRAITER

    # Validation minimale pour la simulation (on pourrait vérifier que les champs carte existent, mais pas nécessaire)
    if not user_id or not subscription_type:
        flash("Erreur lors du traitement (données activation manquantes).", "danger")
        return redirect(url_for('index'))

    # --- La logique d'activation reste la même ---
    try:
        user = User.query.get(user_id)
        if not user or user.subscription_status != 'pending':
            flash("Utilisateur non trouvé ou statut invalide.", "warning")
            return redirect(url_for('register'))

        now = datetime.utcnow()
        start_date = now
        if subscription_type == 'monthly': end_date = start_date + timedelta(days=30)
        elif subscription_type == 'annual': end_date = start_date + timedelta(days=365)
        else: flash("Type d'abonnement invalide.", "danger"); return redirect(url_for('register'))

        user.subscription_status = 'active'
        user.subscription_start_date = start_date
        user.subscription_end_date = end_date

        db.session.commit()

        # Log serveur (SANS données sensibles)
        print(f"SIMULATION PAIEMENT: Activation {subscription_type} pour User ID {user_id}. Données carte reçues mais ignorées.")
        flash("Paiement (simulé) accepté ! Votre compte est activé. Veuillez vous connecter.", "success")
        return redirect(url_for('login'))

    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de l'activation du compte : {e}", "danger")
        print(f"Erreur DB activation compte post-sim-payment: {e}")
        return redirect(url_for('register'))
# --- FIN ROUTE PAIEMENT SIMULÉ ---

# ... (le reste de app.py) ...

# --- NOUVELLE ROUTE : Création Personnel (Gérant) ---
@app.route('/create_staff_user', methods=['POST'])
def create_staff_user():
    # Sécurité : Vérifier si l'utilisateur est gérant
    if session.get('user_role') != 'gerant':
        flash("Action non autorisée.", "danger")
        return redirect(url_for('dashboard'))

    username = request.form.get('username')
    password = request.form.get('password')
    email = request.form.get('email')
    role = request.form.get('role') # Devrait être 'bibliothecaire' depuis le champ caché

    # Validations
    if not username or not password or not role:
        flash("Nom d'utilisateur, mot de passe et rôle sont requis.", "warning")
        return redirect(url_for('dashboard'))
    if role not in ['bibliothecaire', 'prepose']: # Limiter les rôles créables par sécurité
         flash("Rôle invalide pour la création.", "warning")
         return redirect(url_for('dashboard'))

    # Vérifier existence
    existing_user = User.query.filter(or_(User.username == username, User.email == email if email else False)).first()
    if existing_user:
        flash(f"Utilisateur ou email '{username or email}' déjà existant.", "warning")
        return redirect(url_for('dashboard'))

    # Hacher le mot de passe
    hashed_password = generate_password_hash(password)

    # Créer l'utilisateur
    try:
        new_staff = User(
            username=username,
            password=hashed_password,
            email=email if email else None,
            role=role,
            # Pas de détails d'abonnement pour le personnel
            subscription_status='n/a',
            subscription_type='none'
        )
        db.session.add(new_staff)
        db.session.commit()
        flash(f"Compte {role} '{username}' créé avec succès.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la création du compte : {e}", "danger")
        print(f"Erreur DB création staff: {e}")

    return redirect(url_for('dashboard'))
# --- FIN ROUTE Création Personnel ---

# --- NOUVELLE ROUTE : Suppression d'Utilisateur (Gérant) ---
@app.route('/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    # 1. Vérifier si l'utilisateur connecté est Gérant
    if session.get('user_role') != 'gerant':
        flash("Action non autorisée.", "danger")
        return redirect(url_for('dashboard'))

    # 2. Empêcher le gérant de se supprimer lui-même via cette interface
    if user_id == session.get('user_id'):
        flash("Vous ne pouvez pas supprimer votre propre compte.", "warning")
        return redirect(url_for('dashboard'))

    # 3. Trouver l'utilisateur à supprimer
    user_to_delete = User.query.get_or_404(user_id)
    username_deleted = user_to_delete.username
    role_deleted = user_to_delete.role

    # 4. Vérifier qu'on ne supprime pas un autre gérant (sécurité supplémentaire)
    if user_to_delete.role == 'gerant':
         flash("Impossible de supprimer un autre gérant via cette interface.", "danger")
         return redirect(url_for('dashboard'))

    try:
        # 5. Supprimer l'utilisateur (cascade devrait gérer prêts/résas)
        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f"Utilisateur '{username_deleted}' (Rôle: {role_deleted}) supprimé avec succès.", "success")
        print(f"Utilisateur ID {user_id} ({username_deleted}) supprimé par Gérant ID {session.get('user_id')}")

    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la suppression de l'utilisateur : {e}", "danger")
        print(f"Erreur DB suppression utilisateur {user_id}: {e}")

    # 6. Rediriger vers le tableau de bord gérant
    return redirect(url_for('dashboard'))
# --- FIN NOUVELLE ROUTE Suppression Utilisateur ---

# app.py
# ... (imports: Flask, jsonify, request, session, openai, os) ...
# ... (config, chargement clé API, routes existantes) ...

# --- NOUVELLE ROUTE : Endpoint pour le Chatbot IA ---
@app.route('/chat', methods=['POST'])
def chat():
    if not openai.api_key:
        return jsonify({"reply": "Configuration de l'assistant IA manquante."}), 503

    data = request.json
    if not data or 'message' not in data:
        return jsonify({"reply": "Aucun message reçu."}), 400
    user_message = data['message'].strip()
    if not user_message:
        return jsonify({"reply": "Message vide reçu."}), 400

    print(f"[Chatbot Request] Message reçu : '{user_message}'")

    # --- Logique d'interaction avec OpenAI ---
    try:
        # 1. Définir le contexte/prompt système (À ADAPTER !)
        system_prompt = """
        Tu es BiblioBot IA, un assistant virtuel pour la bibliothèque BiblioTech IA.
        Réponds aux questions des utilisateurs de manière concise et amicale, en français.
        Tes connaissances incluent :
        - Horaires : 9h à 18h, lundi au samedi.
        - Recherche : Utiliser la barre de recherche du catalogue.
        - Prêts numériques : 14 jours.
        - Réservations physiques : Possible si livre emprunté.
        - Pour les questions sur la disponibilité d'un livre spécifique ou sur le compte utilisateur, explique que tu ne peux pas accéder à ces informations en temps réel et qu'il faut consulter le catalogue ou le tableau de bord.
        - Refuse poliment les questions hors sujet de la bibliothèque.
        """
        # 2. Choisir le modèle
        model_engine = "gpt-3.5-turbo" # Bon point de départ

        # 3. Faire l'appel API
        print(f"[Chatbot Request] Appel à OpenAI avec model={model_engine}...")
        completion = openai.chat.completions.create(
            model=model_engine,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            max_tokens=150,  # Limiter la réponse pour la vitesse et le coût
            temperature=0.7, # Contrôle la créativité (0 = déterministe, >1 = très créatif)
            n=1,             # Demander une seule réponse
            stop=None        # Pas de séquence d'arrêt spécifique
        )

        # 4. Extraire la réponse texte
        # La structure de la réponse peut légèrement varier, mais c'est souvent ceci :
        bot_reply = completion.choices[0].message.content.strip()

        print(f"[Chatbot Response] Réponse OpenAI reçue: '{bot_reply}'")

        # 5. Renvoyer la réponse au format JSON
        return jsonify({"reply": bot_reply})

    # --- Gestion des erreurs OpenAI spécifiques et génériques ---
    except openai.AuthenticationError as e:
        print(f"[Chatbot Error] Erreur authentification OpenAI: {e}")
        return jsonify({"reply": "Erreur de configuration de l'assistant IA (clé API)."}), 500
    except openai.RateLimitError as e:
        print(f"[Chatbot Error] Limite de taux OpenAI atteinte: {e}")
        return jsonify({"reply": "L'assistant est très sollicité, veuillez réessayer dans un moment."}), 429
    except openai.APITimeoutError as e:
         print(f"[Chatbot Error] Timeout API OpenAI: {e}")
         return jsonify({"reply": "L'assistant IA met trop de temps à répondre, veuillez réessayer."}), 504 # Gateway Timeout
    except Exception as e:
        print(f"[Chatbot Error] Erreur inattendue lors de l'appel OpenAI : {e}")
        # Log l'erreur complète pour le debug serveur si besoin: import traceback; traceback.print_exc()
        return jsonify({"reply": "Désolé, une erreur est survenue en contactant l'assistant IA."}), 500
# --- FIN ROUTE /chat ---

# ... (if __name__ == '__main__':) ...

# --- Bloc d'exécution principal ---
if __name__ == '__main__':
    with app.app_context():
        print("Vérification/Création des tables...")
        # Commentez/décommentez create_all() selon si vous voulez forcer la recréation
        # Attention: supprime les données existantes si vous supprimez le fichier .db
        db.create_all()
        print("Tables OK.")

        # === Section Données de Test (À ADAPTER/DÉCOMMENTER) ===
        # Assurez-vous que les fichiers PDF référencés existent dans instance/uploads/pdfs/
        # --- DEBUT SECTION TEST DATA ---

        # Décommentez pour ajouter les données au premier lancement (après suppression .db)
        # Recommentez ensuite pour éviter les doublons/erreurs.

        if not User.query.first():
           print("Ajout utilisateurs test AVEC MOTS DE PASSE HACHÉS...")
           # Hasher le mot de passe une fois
           hashed_password_default = generate_password_hash('password')
           users = [
               User(username='membre', password=hashed_password_default, role='membre', subscription_status='inactive'), # Ajouter statut par défaut
               User(username='biblio', password=hashed_password_default, role='bibliothecaire', subscription_status='n/a'),
               User(username='prepose', password=hashed_password_default, role='prepose', subscription_status='n/a'),
               User(username='gerant', password=hashed_password_default, role='gerant', subscription_status='n/a')
           ]
           db.session.add_all(users)
           db.session.commit()
           print("Utilisateurs de test ajoutés.")
        else:
            print("Utilisateurs déjà présents (vérifiez si les mots de passe sont hachés).")

        if not Document.query.first():
            print("Ajout documents test...")
            # !! VÉRIFIEZ ET ADAPTEZ CES NOMS DE FICHIERS PDF !!
            pdf1_name = 'fleischmann_l_explosion_du_globe.pdf'
            pdf2_name = 'hermant_la_singuliere_aventure.pdf'
            pdf3_name = 'valles_la_rue.pdf'
            pdf4_name = 'test_document.pdf'

            pdf_files = {
                pdf1_name: os.path.exists(os.path.join(PDF_UPLOAD_FOLDER, pdf1_name)),
                pdf2_name: os.path.exists(os.path.join(PDF_UPLOAD_FOLDER, pdf2_name)),
                pdf3_name: os.path.exists(os.path.join(PDF_UPLOAD_FOLDER, pdf3_name)),
                pdf4_name: os.path.exists(os.path.join(PDF_UPLOAD_FOLDER, pdf4_name))
            }
            for name, exists in pdf_files.items():
                if not exists: print(f"ATTENTION: Fichier PDF '{name}' MANQUANT dans {PDF_UPLOAD_FOLDER}")

            docs = [
                Document(title='Les Miserables', author='Victor Hugo', summary='Fresque sociale épique dans la France du 19e siècle.', status='disponible', is_physical=True, is_digital=False, file_path=None, cover_image_filename=None),
                Document(title='Les Fleurs du mal', author='Charles Baudelaire', summary='Recueil de poèmes explorant la beauté et la décadence.', status='emprunte', is_physical=True, is_digital=False, file_path=None, cover_image_filename=None),
                Document(title='Explosion du globe', author='Hector Fleischmann', summary='Récit apocalyptique.', status='disponible', is_physical=False, is_digital=pdf_files[pdf1_name], file_path=pdf1_name if pdf_files[pdf1_name] else None, cover_image_filename=None),
                Document(title='La Singulière Aventure', author='Abel Hermant', summary='Roman d\'aventure.', status='disponible', is_physical=True, is_digital=pdf_files[pdf2_name], file_path=pdf2_name if pdf_files[pdf2_name] else None, cover_image_filename=None), # Mixte
                Document(title='La Rue', author='Jules Valles', summary='Chronique sociale.', status='disponible', is_physical=True, is_digital=pdf_files[pdf3_name], file_path=pdf3_name if pdf_files[pdf3_name] else None, cover_image_filename=None), # Mixte
                Document(title='Test PDF Seulement', author='TestAuteur', summary='Doc de test.', status='disponible', is_physical=False, is_digital=pdf_files[pdf4_name], file_path=pdf4_name if pdf_files[pdf4_name] else None, cover_image_filename=None),
            ]

            # Filtrer pour ne pas ajouter de doc numérique si le fichier manque
            docs_to_add = [d for d in docs if d.is_physical or (d.is_digital and d.file_path)]
            if docs_to_add:
                 db.session.add_all(docs_to_add); db.session.commit(); print(f"{len(docs_to_add)} documents ajoutés.")
            else: print("Aucun document ajouté (vérifiez fichiers/code).")
        else:
            print("Documents déjà présents.")

        # --- FIN SECTION TEST DATA ---

    # Lancer le serveur Flask
    app.run(debug=True)
# --- Fin Bloc d'exécution ---