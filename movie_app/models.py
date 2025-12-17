from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

# Таблица для связи многие-ко-многим (избранные фильмы)
user_favorites = db.Table('user_favorites',
                          db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
                          db.Column('movie_id', db.Integer, db.ForeignKey('movie.id'), primary_key=True),
                          db.Column('added_at', db.DateTime, default=datetime.utcnow)
                          )


class User(UserMixin, db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(200))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связь с избранными фильмами
    favorite_movies = db.relationship('Movie',
                                      secondary=user_favorites,
                                      backref=db.backref('favorited_by', lazy='dynamic'),
                                      lazy='dynamic')

    # Отношения
    reviews = db.relationship('Review', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def add_favorite(self, movie):
        if not self.is_favorite(movie):
            self.favorite_movies.append(movie)
            return True
        return False

    def remove_favorite(self, movie):
        if self.is_favorite(movie):
            self.favorite_movies.remove(movie)
            return True
        return False

    def is_favorite(self, movie):
        return self.favorite_movies.filter(
            user_favorites.c.movie_id == movie.id
        ).count() > 0

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_admin': self.is_admin,
            'created_at': self.created_at.isoformat(),
            'favorite_count': self.favorite_movies.count()
        }

    reviews = db.relationship('Review', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    favorite_movies = db.relationship('Movie',
                                      secondary=user_favorites,
                                      backref=db.backref('favorited_by', lazy='dynamic'),
                                      lazy='dynamic')

    def __repr__(self):
        return f'<User {self.username}>'


class Movie(db.Model):
    __tablename__ = 'movie'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    director = db.Column(db.String(100))
    description = db.Column(db.Text)
    genre = db.Column(db.String(100))
    rating = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Отношения
    reviews = db.relationship('Review', backref='movie', lazy='dynamic', cascade='all, delete-orphan')

    def update_rating(self):
        if self.reviews.count() > 0:
            from sqlalchemy import func
            avg_rating = db.session.query(func.avg(Review.rating)).filter(
                Review.movie_id == self.id
            ).scalar()
            self.rating = round(float(avg_rating or 0), 1)
        else:
            self.rating = 0.0

    def is_favorite_of(self, user):
        if not user or not user.is_authenticated:
            return False
        return user.is_favorite(self)

    def favorite_count(self):
        return self.favorited_by.count()

    def to_dict(self, user=None):
        data = {
            'id': self.id,
            'title': self.title,
            'year': self.year,
            'director': self.director,
            'description': self.description,
            'genre': self.genre,
            'rating': self.rating,
            'created_at': self.created_at.isoformat(),
            'favorite_count': self.favorite_count(),
            'review_count': self.reviews.count()
        }
        if user and user.is_authenticated:
            data['is_favorite'] = self.is_favorite_of(user)
        return data

    def __repr__(self):
        return f'<Movie {self.title} ({self.year})>'


class Review(db.Model):
    __tablename__ = 'review'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    movie_id = db.Column(db.Integer, db.ForeignKey('movie.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Ограничения
    __table_args__ = (
        db.UniqueConstraint('user_id', 'movie_id', name='unique_user_movie_review'),
        db.CheckConstraint('rating >= 1 AND rating <= 5', name='rating_range_check'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'content': self.content,
            'rating': self.rating,
            'user_id': self.user_id,
            'movie_id': self.movie_id,
            'created_at': self.created_at.isoformat(),
            'username': self.user.username if self.user else None,
            'movie_title': self.movie.title if self.movie else None
        }

    def __repr__(self):
        return f'<Review {self.id} by User {self.user_id} for Movie {self.movie_id}>'
