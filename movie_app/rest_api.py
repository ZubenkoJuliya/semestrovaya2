# rest_api.py
from flask_restful import Resource, reqparse
from flask_login import login_required, current_user
from flask import jsonify
from models import db, User, Movie, Review


# Парсеры для API
movie_parser = reqparse.RequestParser()
movie_parser.add_argument('title', required=True, help='Название фильма обязательно')
movie_parser.add_argument('year', type=int, required=True, help='Год выпуска обязателен')
movie_parser.add_argument('director')
movie_parser.add_argument('description')
movie_parser.add_argument('genre')

review_parser = reqparse.RequestParser()
review_parser.add_argument('content', required=True, help='Текст отзыва обязателен')
review_parser.add_argument('rating', type=int, required=True, help='Оценка (1-5) обязательна')


# API для фильмов
class MovieListAPI(Resource):
    def get(self):
        # Список всех фильмов
        movies = Movie.query.all()
        return jsonify([movie.to_dict(current_user) for movie in movies])

    @login_required
    def post(self):
        # Добавить новый фильм (только админ)
        if not current_user.is_admin:
            return {'error': 'Только администраторы могут добавлять фильмы'}, 403

        args = movie_parser.parse_args()

        movie = Movie(
            title=args['title'],
            year=args['year'],
            director=args.get('director'),
            description=args.get('description'),
            genre=args.get('genre')
        )

        db.session.add(movie)
        db.session.commit()

        return movie.to_dict(current_user), 201


class MovieAPI(Resource):
    def get(self, movie_id):
        # Информацию о фильме по ID
        movie = Movie.query.get_or_404(movie_id)
        return jsonify(movie.to_dict(current_user))

    @login_required
    def put(self, movie_id):
        # Обновить информацию о фильме (только админ)
        if not current_user.is_admin:
            return {'error': 'Только администраторы могут редактировать фильмы'}, 403

        movie = Movie.query.get_or_404(movie_id)
        args = movie_parser.parse_args()

        movie.title = args['title']
        movie.year = args['year']
        movie.director = args.get('director')
        movie.description = args.get('description')
        movie.genre = args.get('genre')

        db.session.commit()
        return movie.to_dict(current_user)

    @login_required
    def delete(self, movie_id):
        # Удалить фильм (только админ)
        if not current_user.is_admin:
            return {'error': 'Только администраторы могут удалять фильмы'}, 403

        movie = Movie.query.get_or_404(movie_id)
        db.session.delete(movie)
        db.session.commit()
        return {'message': 'Фильм удален'}


# API для отзывов
class ReviewListAPI(Resource):
    def get(self, movie_id):
        # Получить все отзывы к фильму
        reviews = Review.query.filter_by(movie_id=movie_id).all()
        return jsonify([review.to_dict() for review in reviews])

    @login_required
    def post(self, movie_id):
        # Добавить отзыв к фильму
        args = review_parser.parse_args()

        # Проверяем, есть ли уже отзыв от этого пользователя
        existing = Review.query.filter_by(
            movie_id=movie_id,
            user_id=current_user.id
        ).first()

        if existing:
            return {'error': 'Вы уже оставляли отзыв на этот фильм'}, 400

        review = Review(
            content=args['content'],
            rating=args['rating'],
            user_id=current_user.id,
            movie_id=movie_id
        )

        db.session.add(review)

        # Обновляем рейтинг фильма
        movie = Movie.query.get(movie_id)
        if movie:
            movie.update_rating()

        db.session.commit()
        return review.to_dict(), 201


class ReviewAPI(Resource):
    def get(self, review_id):
        # Получить отзыв по ID
        review = Review.query.get_or_404(review_id)
        return jsonify(review.to_dict())

    @login_required
    def delete(self, review_id):
        # Удалить отзыв (только автор или админ)
        review = Review.query.get_or_404(review_id)

        if review.user_id != current_user.id and not current_user.is_admin:
            return {'error': 'Вы не можете удалить этот отзыв'}, 403

        movie_id = review.movie_id
        db.session.delete(review)

        # Обновляем рейтинг фильма
        movie = Movie.query.get(movie_id)
        if movie:
            movie.update_rating()

        db.session.commit()
        return {'message': 'Отзыв удален'}


# API для пользователей
class UserListAPI(Resource):
    @login_required
    def get(self):
        # Получить список пользователей (только админ)
        if not current_user.is_admin:
            return {'error': 'Только администраторы могут просматривать список пользователей'}, 403

        users = User.query.all()
        return jsonify([user.to_dict() for user in users])


class UserAPI(Resource):
    @login_required
    def get(self, user_id):
        # Получить информацию о пользователе
        if current_user.id != user_id and not current_user.is_admin:
            return {'error': 'Доступ запрещен'}, 403

        user = User.query.get_or_404(user_id)
        return jsonify(user.to_dict())


# API для избранного
class FavoriteAPI(Resource):
    @login_required
    def post(self, movie_id):
        # Добавить фильм в избранное
        movie = Movie.query.get_or_404(movie_id)

        if current_user.is_favorite(movie):
            return {'error': 'Фильм уже в избранном'}, 400

        current_user.add_favorite(movie)
        db.session.commit()

        return {
            'message': 'Фильм добавлен в избранное',
            'is_favorite': True,
            'favorite_count': movie.favorite_count()
        }, 201

    @login_required
    def delete(self, movie_id):
        # Удалить фильм из избранного
        movie = Movie.query.get_or_404(movie_id)

        if not current_user.is_favorite(movie):
            return {'error': 'Фильм не в избранном'}, 400

        current_user.remove_favorite(movie)
        db.session.commit()

        return {
            'message': 'Фильм удален из избранного',
            'is_favorite': False,
            'favorite_count': movie.favorite_count()
        }

    @login_required
    def get(self, movie_id):
        # Проверить, в избранном ли фильм
        movie = Movie.query.get_or_404(movie_id)
        is_favorite = current_user.is_favorite(movie)

        return {
            'is_favorite': is_favorite,
            'favorite_count': movie.favorite_count()
        }


class FavoriteListAPI(Resource):
    @login_required
    def get(self):
        # Получить список избранных фильмов пользователя
        favorites = current_user.favorite_movies.all()
        return jsonify([movie.to_dict(current_user) for movie in favorites])


def register_api_resources(api):
    """Регистрация всех API ресурсов"""
    api.add_resource(MovieListAPI, '/movies/')
    api.add_resource(MovieAPI, '/movies/<int:movie_id>')
    api.add_resource(ReviewListAPI, '/movies/<int:movie_id>/reviews/')
    api.add_resource(ReviewAPI, '/reviews/<int:review_id>')
    api.add_resource(UserListAPI, '/users/')
    api.add_resource(UserAPI, '/users/<int:user_id>')
    api.add_resource(FavoriteAPI, '/movies/<int:movie_id>/favorite/')
    api.add_resource(FavoriteListAPI, '/users/me/favorites/')