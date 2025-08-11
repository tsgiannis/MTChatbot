from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_cors import CORS
import unicodedata
import spacy  # pip install spacy; python -m spacy download el_core_news_sm
from difflib import SequenceMatcher
from collections import defaultdict
import sqlite3  # Built-in, no installation needed
import os

app = Flask(__name__)
CORS(app)

# Load SpaCy's Greek model (CPU-only, ~40MB)
nlp = spacy.load("el_core_news_sm", disable=["parser", "ner"])  # Disable unused components for speed

# SQLite Database Setup
DB_FILE = 'faqs.db'


def init_db():
    """Initialize the SQLite database if it doesn't exist."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_name TEXT UNIQUE NOT NULL,
            answer TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS references_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            reference_question TEXT NOT NULL,
            FOREIGN KEY (topic_id) REFERENCES topics (id)
        )
    """)
    conn.commit()
    conn.close()


# Call init_db on app start
init_db()


def add_or_update_topic(topic_name, answer, references):
    """Add or update a topic with its answer and reference questions."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Insert or replace topic
    cursor.execute('''
        INSERT OR REPLACE INTO topics (topic_name, answer)
        VALUES (?, ?)
    ''', (topic_name, answer))
    topic_id = cursor.execute('SELECT id FROM topics WHERE topic_name = ?', (topic_name,)).fetchone()[0]
    # Delete existing references for this topic
    cursor.execute('DELETE FROM references WHERE topic_id = ?', (topic_id,))
    # Insert new references
    for ref in references:
        cursor.execute('''
            INSERT INTO references (topic_id, reference_question)
            VALUES (?, ?)
        ''', (topic_id, ref))
    conn.commit()
    conn.close()


def load_faqs_from_db():
    """Load FAQs from database and build inverted index and metadata."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    faqs = {}
    inverted_index = defaultdict(list)
    faq_metadata = {}

    # Load topics
    cursor.execute('SELECT id, topic_name, answer FROM topics')
    for topic_id, topic_name, answer in cursor.fetchall():
        faqs[topic_name] = {'references': [], 'answer': answer}

    # Load references
    cursor.execute('SELECT topic_id, reference_question FROM references_table')
    for topic_id, ref in cursor.fetchall():
        cursor2 = conn.cursor()
        cursor2.execute('SELECT topic_name FROM topics WHERE id = ?', (topic_id,))
        topic_name = cursor2.fetchone()[0]
        faqs[topic_name]['references'].append(ref)

    # Process for index
    for topic_name in faqs:
        for idx, ref in enumerate(faqs[topic_name]['references']):
            lemm_tokens = tokenize_and_lemmatize(ref)
            joined_lemm = ' '.join(lemm_tokens)
            lemm_set = set(lemm_tokens)
            faq_metadata[(topic_name, idx)] = {
                'joined': joined_lemm,
                'set': lemm_set,
                'answer': faqs[topic_name]['answer']
            }
            for token in lemm_set:
                inverted_index[token].append((topic_name, idx))

    conn.close()
    return inverted_index, faq_metadata


# Load FAQs on app start (can be reloaded if needed)
inverted_index, faq_metadata = load_faqs_from_db()


def normalize(text):
    """Normalize Greek text by lowercasing and removing diacritics."""
    text = text.lower()
    text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
    return text


def tokenize_and_lemmatize(text):
    """Tokenize and lemmatize text using SpaCy, keeping all tokens including stop words."""
    norm_text = normalize(text)
    doc = nlp(norm_text)
    return [token.lemma_ for token in doc]


def jaccard_similarity(set1, set2):
    """Compute Jaccard similarity between two sets."""
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union if union != 0 else 0.0


@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    if 'message' not in data:
        return jsonify({'error': 'No message provided'}), 400

    prompt = data['message']
    lemm_tokens = tokenize_and_lemmatize(prompt)
    joined_prompt = ' '.join(lemm_tokens)
    prompt_set = set(lemm_tokens)

    # Use inverted index to find relevant references
    candidate_refs = set()
    for token in prompt_set:
        candidate_refs.update(inverted_index.get(token, []))

    best_topic = None
    best_idx = None
    best_score = 0.0
    use_jaccard = True  # Toggle to False to use SequenceMatcher

    for topic, idx in candidate_refs:
        ref = faq_metadata[(topic, idx)]
        if use_jaccard:
            score = jaccard_similarity(prompt_set, ref['set'])
        else:
            score = SequenceMatcher(None, joined_prompt, ref['joined']).ratio()
        if score > best_score:
            best_score = score
            best_topic = topic
            best_idx = idx

    threshold = 0.6 if use_jaccard else 0.7  # Adjust based on scoring method
    if best_score >= threshold and best_topic:
        return jsonify({
            'reply': faq_metadata[(best_topic, best_idx)]['answer'],
            'probability': round(best_score, 3),
            'lemmatized_tokens': lemm_tokens
        })
    else:
        return jsonify({
            'reply': 'Δεν καταλαβαίνω την ερώτηση. Παρακαλώ δοκιμάστε ξανά με διαφορετική διατύπωση.',
            'probability': 0.0,
            'lemmatized_tokens': lemm_tokens
        })


@app.route('/add_faq', methods=['POST'])
def add_faq():
    data = request.json
    if 'topic' not in data or 'answer' not in data or 'references' not in data:
        return jsonify({'error': 'Missing required fields: topic, answer, references'}), 400

    topic = data['topic']
    answer = data['answer']
    references = data['references']  # List of strings

    add_or_update_topic(topic, answer, references)

    # Reload index after update
    global inverted_index, faq_metadata
    inverted_index, faq_metadata = load_faqs_from_db()

    return jsonify({'success': True, 'message': 'FAQ added/updated successfully'})


# New Frontend Routes for Admin Page

@app.route('/admin', methods=['GET'])
def admin():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT topic_name FROM topics ORDER BY topic_name')
    topics = [row[0] for row in cursor.fetchall()]
    conn.close()
    return render_template('admin.html', topics=topics)


@app.route('/edit/<topic_name>', methods=['GET', 'POST'])
def edit_topic(topic_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if request.method == 'POST':
        answer = request.form['answer']
        references = request.form['references'].splitlines()  # Assume questions separated by newlines
        references = [ref.strip() for ref in references if ref.strip()]

        add_or_update_topic(topic_name, answer, references)

        # Reload index
        global inverted_index, faq_metadata
        inverted_index, faq_metadata = load_faqs_from_db()

        return redirect(url_for('admin'))

    # GET: Load existing data
    cursor.execute('SELECT answer FROM topics WHERE topic_name = ?', (topic_name,))
    answer_row = cursor.fetchone()
    if not answer_row:
        return 'Topic not found', 404
    answer = answer_row[0]

    cursor.execute('''
        SELECT reference_question FROM references
        WHERE topic_id = (SELECT id FROM topics WHERE topic_name = ?)
    ''', (topic_name,))
    references = [row[0] for row in cursor.fetchall()]
    references_text = '\n'.join(references)

    conn.close()
    return render_template('edit.html', topic_name=topic_name, answer=answer, references_text=references_text)


@app.route('/add', methods=['GET', 'POST'])
def add_topic():
    if request.method == 'POST':
        topic_name = request.form['topic_name']
        answer = request.form['answer']
        references = request.form['references'].splitlines()
        references = [ref.strip() for ref in references if ref.strip()]

        add_or_update_topic(topic_name, answer, references)

        # Reload index
        global inverted_index, faq_metadata
        inverted_index, faq_metadata = load_faqs_from_db()

        return redirect(url_for('admin'))

    return render_template('add.html')


# Optional: Seed initial data (uncomment if needed)
# add_or_update_topic(
#     'decentralized_administration',
#     "Η Αποκεντρωμένη Διοίκηση στην Ελλάδα είναι ένας θεσμός που λειτουργεί ως ενδιάμεσο επίπεδο μεταξύ κεντρικής κυβέρνησης και τοπικής αυτοδιοίκησης. Ο ρόλος της περιλαμβάνει τον έλεγχο νομιμότητας πράξεων της τοπικής αυτοδιοίκησης, την εποπτεία δημόσιων υπηρεσιών σε περιφερειακό επίπεδο και την υλοποίηση πολιτικών του κράτους σε τομείς όπως περιβάλλον, πολεοδομία και υγεία.",
#     [
#         "Πες μου για την Αποκεντρωμένη Διοίκηση",
#         "Ποιος είναι ο ρόλος των Αποκεντρωμένων Διοικήσεων",
#         "Τι ξέρεις για τις Αποκεντρωμένες Διοικήσεις"
#     ]
# )

if __name__ == '__main__':
    app.run(debug=True,use_reloader=False)