# app.py
import os
import pandas as pd
from flask import Flask, render_template, request, jsonify
from transformers import pipeline
from pydub import AudioSegment
import speech_recognition as sr
import logging
import time

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# Load reviews.csv into DataFrame
reviews_df = pd.read_csv('reviews.csv')

AUDIO_DIR = "audio_files"  
TEMP_AUDIO = "temp_audio.wav"

# Initialize sentiment analysis pipeline
sentiment_pipeline = pipeline("sentiment-analysis", model="cardiffnlp/twitter-roberta-base-sentiment")

logging.info("Columns in the DataFrame: %s", reviews_df.columns)

def fetch_reviews_and_rating(product_name):
    logging.info(f"Fetching reviews and rating for product: {product_name}")

    # Strip spaces from product name for matching
    normalized_name = product_name.replace(" ", "").lower()
    product_data = reviews_df[reviews_df['product'].str.replace(" ", "").str.lower() == normalized_name]
    
    if product_data.empty:
        logging.error(f"No reviews found for product: {product_name}")
        return ["No reviews found."], [], None  

    reviews = product_data['review'].tolist()
    audio_files = product_data['audio_files'].tolist()

    if not audio_files or pd.isna(audio_files[0]) or audio_files[0] == '':
        logging.warning(f"No audio files available for {product_name}")
        audio_files = []  

    try:
        rating = int(product_data['rating'].iloc[0]) if not pd.isna(product_data['rating'].iloc[0]) else None
    except (ValueError, TypeError):
        rating = None

    return reviews, audio_files, rating

def transcribe_audio(file_path):
    recognizer = sr.Recognizer()
    with sr.AudioFile(file_path) as source:
        audio_data = recognizer.record(source)
        try:
            text = recognizer.recognize_google(audio_data)
            return text
        except sr.UnknownValueError:
            return "Could not understand the audio."
        except sr.RequestError as e:
            return f"Could not request results from the speech recognition service; {e}"

def analyze_sentiment(reviews):
    if not reviews:
        return "No reviews found."

    sentiments = sentiment_pipeline(reviews)
    logging.info(f"Sentiments: {sentiments}")  

    positive = sum(1 for sentiment in sentiments if sentiment['label'] == 'LABEL_2')  
    negative = sum(1 for sentiment in sentiments if sentiment['label'] == 'LABEL_0')  
    neutral = sum(1 for sentiment in sentiments if sentiment['label'] == 'LABEL_1') 

    if positive > negative and positive > neutral:
        return "good"
    elif negative > positive and negative > neutral:
        return "bad"
    else:
        return "average"
def save_uploaded_file(file):
    if not os.path.exists(AUDIO_DIR):
        os.makedirs(AUDIO_DIR) 

    base_name = os.path.splitext(file.filename)[0]
    extension = os.path.splitext(file.filename)[1]
    new_filename = f"{base_name}_{int(time.time())}{extension}"
    
    upload_path = os.path.join(AUDIO_DIR, new_filename)
    file.save(upload_path)
    
    return upload_path 

@app.route('/submit_review', methods=['POST'])
def submit_review():
    data = request.json
    product_name = data.get('product_name')
    review_text = data.get('review_text')
    audio_file_path = data.get('audio_file_path')
    rating = data.get('rating')

    new_review = pd.DataFrame({
        'product': [product_name],
        'review': [review_text],
        'audio_files': [audio_file_path],
        'rating': [rating],
        'review_date': [pd.Timestamp.now()],
        'reviewer_name': ['Anonymous'],
        'purchase_location': ['Online']
    })

    global reviews_df
    reviews_df = pd.concat([reviews_df, new_review], ignore_index=True)
    reviews_df.to_csv('reviews.csv', index=False)  

    return jsonify({'message': 'Review submitted successfully!'})

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    data = request.json
    feedback_text = data.get('feedback_text')

    feedback_df = pd.DataFrame({
        'feedback_text': [feedback_text],
        'feedback_date': [pd.Timestamp.now()],
    })

    if os.path.exists('feedback.csv'):
        feedback_df.to_csv('feedback.csv', mode='a', header=False, index=False)  
    else:
        feedback_df.to_csv('feedback.csv', index=False)  

    return jsonify({'message': 'Feedback submitted successfully!'})

@app.route('/upload_audio', methods=['POST'])
def upload_audio():
    if 'audio_file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['audio_file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    audio_file_path = save_uploaded_file(file)
    return jsonify({'audio_file_path': audio_file_path})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    product_name = data.get('product_name')
    reviews, audio_files, rating = fetch_reviews_and_rating(product_name)

    audio_reviews = []
    for audio_file in audio_files:
        if isinstance(audio_file, str) and os.path.isfile(audio_file):
            logging.info(f"Transcribing file: {audio_file}")

            if audio_file.endswith(".mp3"):
                sound = AudioSegment.from_mp3(audio_file)
                audio_file = TEMP_AUDIO
                sound.export(audio_file, format="wav")

            transcription = transcribe_audio(audio_file)
            if transcription not in ["Could not understand the audio.", "Could not request results from the speech recognition service; {e}"]:
                audio_reviews.append(transcription)
        else:
            logging.info(f"No valid audio file for {product_name}, skipping audio processing.")

    reviews.extend(audio_reviews)

    if not reviews:
        return jsonify({'sentiment_message': f"No reviews found for {product_name}.", 'rating': rating})

    sentiment = analyze_sentiment(reviews)

    rating = int(rating) if rating is not None else "No rating available"

    sentiment_message = f"This product {product_name} is {sentiment}."
    return jsonify({'sentiment_message': sentiment_message, 'rating': rating})

if __name__ == '__main__':
    app.run(debug=True)