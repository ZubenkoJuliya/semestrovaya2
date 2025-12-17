from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, NumberRange
from flask_restful import Api, Resource, reqparse
from models import db, User, Movie, Review, user_favorites
from config import Config

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///movies.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config.from_object(Config)

# Инициализация
db.init_app(app)
api = Api(app, prefix='/api/v1')
login_manager = LoginManager(app)
login_manager.login_view = 'login'


# Формы для веб-части
class LoginForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')


class RegisterForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email (необязательно)', validators=[Length(max=120)])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(min=6)])
    password2 = PasswordField('Повторите пароль', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Зарегистрироваться')


class MovieForm(FlaskForm):
    title = StringField('Название', validators=[DataRequired()])
    year = IntegerField('Год', validators=[DataRequired(), NumberRange(min=1900, max=2100)])
    director = StringField('Режиссер')
    description = TextAreaField('Описание')
    genre = StringField('Жанр')
    submit = SubmitField('Сохранить')


class ReviewForm(FlaskForm):
    content = TextAreaField('Отзыв', validators=[DataRequired(), Length(min=10)])
    rating = IntegerField('Оценка (1-5)', validators=[DataRequired(), NumberRange(min=1, max=5)])
    submit = SubmitField('Добавить отзыв')


# ========== REST API РЕСУРСЫ ==========

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
        """Получить список всех фильмов"""
        movies = Movie.query.all()
        return jsonify([movie.to_dict(current_user) for movie in movies])

    @login_required
    def post(self):
        """Добавить новый фильм (только админ)"""
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
        """Получить информацию о фильме по ID"""
        movie = Movie.query.get_or_404(movie_id)
        return jsonify(movie.to_dict(current_user))

    @login_required
    def put(self, movie_id):
        """Обновить информацию о фильме (только админ)"""
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
        """Удалить фильм (только админ)"""
        if not current_user.is_admin:
            return {'error': 'Только администраторы могут удалять фильмы'}, 403

        movie = Movie.query.get_or_404(movie_id)
        db.session.delete(movie)
        db.session.commit()
        return {'message': 'Фильм удален'}


# API для отзывов
class ReviewListAPI(Resource):
    def get(self, movie_id):
        """Получить все отзывы к фильму"""
        reviews = Review.query.filter_by(movie_id=movie_id).all()
        return jsonify([review.to_dict() for review in reviews])

    @login_required
    def post(self, movie_id):
        """Добавить отзыв к фильму"""
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
        """Получить отзыв по ID"""
        review = Review.query.get_or_404(review_id)
        return jsonify(review.to_dict())

    @login_required
    def delete(self, review_id):
        """Удалить отзыв (только автор или админ)"""
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
        """Получить список пользователей (только админ)"""
        if not current_user.is_admin:
            return {'error': 'Только администраторы могут просматривать список пользователей'}, 403

        users = User.query.all()
        return jsonify([user.to_dict() for user in users])


class UserAPI(Resource):
    @login_required
    def get(self, user_id):
        """Получить информацию о пользователе"""
        if current_user.id != user_id and not current_user.is_admin:
            return {'error': 'Доступ запрещен'}, 403

        user = User.query.get_or_404(user_id)
        return jsonify(user.to_dict())


# API для избранного
class FavoriteAPI(Resource):
    @login_required
    def post(self, movie_id):
        """Добавить фильм в избранное"""
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
        """Удалить фильм из избранного"""
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
        """Проверить, в избранном ли фильм"""
        movie = Movie.query.get_or_404(movie_id)
        is_favorite = current_user.is_favorite(movie)

        return {
            'is_favorite': is_favorite,
            'favorite_count': movie.favorite_count()
        }


class FavoriteListAPI(Resource):
    @login_required
    def get(self):
        """Получить список избранных фильмов пользователя"""
        favorites = current_user.favorite_movies.all()
        return jsonify([movie.to_dict(current_user) for movie in favorites])


# Регистрация API endpoints
api.add_resource(MovieListAPI, '/movies/')
api.add_resource(MovieAPI, '/movies/<int:movie_id>')
api.add_resource(ReviewListAPI, '/movies/<int:movie_id>/reviews/')
api.add_resource(ReviewAPI, '/reviews/<int:review_id>')
api.add_resource(UserListAPI, '/users/')
api.add_resource(UserAPI, '/users/<int:user_id>')
api.add_resource(FavoriteAPI, '/movies/<int:movie_id>/favorite/')
api.add_resource(FavoriteListAPI, '/users/me/favorites/')


# ========== ВЕБ-ЧАСТЬ ==========

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def init_db():
    """Инициализация базы данных"""
    with app.app_context():
        db.create_all()
        # Создаем тестовые данные если база пустая
        if Movie.query.count() == 0:
            # Создаем админа
            admin = User(username='admin', email='admin@example.com', is_admin=True)
            admin.set_password('admin123')
            db.session.add(admin)

            # Создаем обычного пользователя
            user = User(username='user', email='user@example.com')
            user.set_password('user123')
            db.session.add(user)

            # Добавляем БОЛЬШЕ крутых фильмов!
            movies = [
                # Классика мирового кино
                Movie(title='Интерстеллар', year=2014, director='Кристофер Нолан',
                      genre='Фантастика, Драма',
                      description='Фантастический эпос о космических путешествиях, поиске нового дома для человечества и силе любви.'),

                Movie(title='Крестный отец', year=1972, director='Фрэнсис Форд Коппола',
                      genre='Криминал, Драма',
                      description='Эпическая история мафиозной семьи Корлеоне в послевоенной Америке.'),

                Movie(title='Побег из Шоушенка', year=1994, director='Фрэнк Дарабонт',
                      genre='Драма',
                      description='История о надежде и свободе в тюрьме строгого режима.'),

                Movie(title='Начало', year=2010, director='Кристофер Нолан',
                      genre='Фантастика, Боевик',
                      description='Талантливый вор, промышляющий в мире снов, получает задание не украсть, а внедрить идею.'),

                Movie(title='Темный рыцарь', year=2008, director='Кристофер Нолан',
                      genre='Боевик, Криминал',
                      description='Бэтмен, комиссар Гордон и прокурор Харви Дент ведут войну с криминалом в Готэме.'),

                Movie(title='Форрест Гамп', year=1994, director='Роберт Земекис',
                      genre='Драма, Мелодрама',
                      description='История простого человека, ставшего свидетелем ключевых событий американской истории.'),

                Movie(title='Список Шиндлера', year=1993, director='Стивен Спилберг',
                      genre='Драма, Биография',
                      description='Немецкий предприниматель Оскар Шиндлер спасает более тысячи евреев во время Холокоста.'),

                Movie(title='Властелин колец: Возвращение короля', year=2003, director='Питер Джексон',
                      genre='Фэнтези, Приключения',
                      description='Завершение эпической трилогии о борьбе за Кольцо Всевластия.'),

                Movie(title='Бойцовский клуб', year=1999, director='Дэвид Финчер',
                      genre='Драма, Триллер',
                      description='История офисного работника, который встречает загадочного торговца мылом и создает подпольный бойцовский клуб.'),

                # Современные хиты
                Movie(title='Джентльмены', year=2019, director='Гай Ричи',
                      genre='Криминал, Комедия',
                      description='Американский наркобарон пытается продать свой бизнес лондонскому олигарху.'),

                Movie(title='Дюна', year=2021, director='Дени Вильнёв',
                      genre='Фантастика, Драма',
                      description='Пол Атрейдес отправляется на опасную планету Арракис, чтобы защитить будущее своей семьи и народа.'),

                Movie(title='Оппенгеймер', year=2023, director='Кристофер Нолан',
                      genre='Драма, Биография',
                      description='История создания атомной бомбы и моральная дилемма ее создателя.'),

                Movie(title='Аватар', year=2009, director='Джеймс Кэмерон',
                      genre='Фантастика, Приключения',
                      description='Парализованный морпех становится частью программы по освоению планеты Пандора.'),

                Movie(title='Джокер', year=2019, director='Тодд Филлипс',
                      genre='Драма, Криминал',
                      description='История превращения неудачливого комика в психопата-преступника.'),

                # Российское кино
                Movie(title='Брат', year=1997, director='Алексей Балабанов',
                      genre='Криминал, Драма',
                      description='Демобилизованный солдат Данила Багров становится наемным убийцей в Петербурге.'),

                Movie(title='Легенда №17', year=2013, director='Николай Лебедев',
                      genre='Драма, Спорт',
                      description='История хоккеиста Валерия Харламова и легендарной суперсерии СССР-Канада 1972 года.'),

                Movie(title='Движение вверх', year=2017, director='Антон Мегердичев',
                      genre='Драма, Спорт',
                      description='История победы сборной СССР по баскетболу над американцами на Олимпиаде-1972.'),

                # Популярные сериалы (как фильмы)
                Movie(title='Игра престолов (сериал)', year=2011, director='Дэвид Бениофф, Д.Б. Уайсс',
                      genre='Фэнтези, Драма',
                      description='Борьба за Железный Трон в вымышленном мире Вестероса.'),

                Movie(title='Во все тяжкие (сериал)', year=2008, director='Винс Гиллиган',
                      genre='Криминал, Драма',
                      description='Школьный учитель химии становится наркобароном после того, как узнает, что болен раком.'),

                # Комедии
                Movie(title='Иван Васильевич меняет профессию', year=1973, director='Леонид Гайдай',
                      genre='Комедия, Фантастика',
                      description='Изобретатель Шурик создает машину времени и случайно отправляет управдома в прошлое.'),

                Movie(title='Один дома', year=1990, director='Крис Коламбус',
                      genre='Комедия, Семейный',
                      description='8-летний Кевин остался один дома и защищает свой дом от грабителей.'),

                # Аниме
                Movie(title='Унесенные призраками', year=2001, director='Хаяо Миядзаки',
                      genre='Аниме, Фэнтези',
                      description='Девочка Тихиро попадает в мир духов и пытается спасти своих родителей.'),

                Movie(title='Твоё имя', year=2016, director='Макото Синкай',
                      genre='Аниме, Мелодрама',
                      description='Парень и девушка из разных городов обнаруживают, что меняются телами во сне.'),

                # Научная фантастика
                Movie(title='Матрица', year=1999, director='Братья Вачовски',
                      genre='Фантастика, Боевик',
                      description='Хакер по имени Нео узнает, что мир, в котором он живет - это компьютерная симуляция.'),

                Movie(title='Бегущий по лезвию 2049', year=2017, director='Дени Вильнёв',
                      genre='Фантастика, Драма',
                      description='Охотник на андроидов раскрывает секрет, способный разрушить общество.'),

                # Ужасы
                Movie(title='Сияние', year=1980, director='Стэнли Кубрик',
                      genre='Ужасы, Драма',
                      description='Писатель с семьей поселяется в отеле, где на него воздействуют злые силы.'),

                Movie(title='Оно', year=2017, director='Андрес Мускетти',
                      genre='Ужасы',
                      description='Группа детей из городка Дерри сталкивается со злобным клоуном Пеннивайзом.'),

                # Драмы
                Movie(title='Зеленая книга', year=2018, director='Питер Фаррелли',
                      genre='Драма, Комедия',
                      description='Путешествие афроамериканского пианиста и его итальянского водителя по югу США в 1960-х.'),

                Movie(title='1+1', year=2011, director='Оливье Накаш',
                      genre='Драма, Комедия',
                      description='Парализованный аристократ нанимает в сиделки бывшего заключенного.')
            ]

            for movie in movies:
                db.session.add(movie)

            db.session.commit()

            # Добавляем тестовые отзывы
            reviews = [
                Review(content='Невероятное кино! Графика и сюжет на высоте.', rating=5, user_id=1, movie_id=1),
                Review(content='Классика, которую должен посмотреть каждый.', rating=5, user_id=2, movie_id=2),
                Review(content='Трогательная история о надежде.', rating=5, user_id=1, movie_id=3),
                Review(content='Гениальный сюжет, Кристофер Нолан - гений!', rating=5, user_id=2, movie_id=4),
                Review(content='Лучший фильм про Бэтмена, Хит Леджер великолепен!', rating=5, user_id=1, movie_id=5),
                Review(content='Потрясающая актерская игра Тома Хэнкса.', rating=4, user_id=2, movie_id=6),
                Review(content='Тяжелый, но важный фильм о войне.', rating=5, user_id=1, movie_id=7),
                Review(content='Эпическое завершение трилогии.', rating=5, user_id=2, movie_id=8),
                Review(content='Культовый фильм Тарантино.', rating=4, user_id=1, movie_id=9),
                Review(content='Фильм, который меняет мировоззрение.', rating=5, user_id=2, movie_id=10)
            ]

            for review in reviews:
                db.session.add(review)

            db.session.commit()

            # Обновляем рейтинги фильмов
            for movie in Movie.query.all():
                movie.update_rating()

            db.session.commit()


# Веб-маршруты
@app.route('/')
def index():
    """Главная страница"""
    # Показываем топ фильмов и новые фильмы
    top_movies = Movie.query.order_by(Movie.rating.desc()).limit(6).all()
    new_movies = Movie.query.order_by(Movie.created_at.desc()).limit(6).all()

    # Только для админов показываем статистику
    movie_count = user_count = review_count = None
    if current_user.is_authenticated and current_user.is_admin:
        from models import User, Review
        movie_count = Movie.query.count()
        user_count = User.query.count()
        review_count = Review.query.count()

    return render_template('index.html',
                           top_movies=top_movies,
                           new_movies=new_movies,
                           movie_count=movie_count,
                           user_count=user_count,
                           review_count=review_count)


@app.route('/movies')
def movie_list():
    """Список всех фильмов"""
    page = request.args.get('page', 1, type=int)
    genre_filter = request.args.get('genre')
    search_query = request.args.get('search')

    query = Movie.query

    if genre_filter:
        query = query.filter(Movie.genre.ilike(f'%{genre_filter}%'))

    if search_query:
        query = query.filter(Movie.title.ilike(f'%{search_query}%'))

    movies = query.order_by(Movie.title).paginate(page=page, per_page=12)

    # Получаем все жанры для фильтра
    genres = db.session.query(Movie.genre).distinct().all()
    genre_list = [g[0] for g in genres if g[0]]

    return render_template('movie_list.html', movies=movies, genres=genre_list)


@app.route('/movie/<int:movie_id>', methods=['GET', 'POST'])
def movie_detail(movie_id):
    """Страница фильма - доступна ВСЕМ пользователям"""
    movie = Movie.query.get_or_404(movie_id)

    # Отзывы видят ВСЕ
    reviews = Review.query.filter_by(movie_id=movie_id).order_by(Review.created_at.desc()).all()

    form = ReviewForm()

    # Только авторизованные могут оставлять отзывы
    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash('Войдите, чтобы оставить отзыв', 'warning')
            return redirect(url_for('login'))

        review = Review(
            content=form.content.data,
            rating=form.rating.data,
            user_id=current_user.id,
            movie_id=movie_id
        )
        db.session.add(review)
        movie.update_rating()
        db.session.commit()
        flash('Отзыв добавлен!', 'success')
        return redirect(url_for('movie_detail', movie_id=movie_id))

    # Проверяем избранное (только для авторизованных)
    is_favorite = False
    if current_user.is_authenticated:
        if hasattr(current_user, 'is_favorite'):
            try:
                is_favorite = current_user.is_favorite(movie)
            except:
                is_favorite = False

    return render_template('movie_detail.html',
                           movie=movie,
                           reviews=reviews,
                           form=form,
                           is_favorite=is_favorite)


@app.route('/movie/<int:movie_id>/favorite', methods=['POST'])
@login_required
def toggle_favorite(movie_id):
    """Добавить/удалить фильм из избранного"""
    # Эта декоратор @login_required уже проверяет авторизацию

    movie = Movie.query.get_or_404(movie_id)

    # Безопасная проверка
    try:
        # Проверяем, добавлен ли уже фильм в избранное
        is_currently_favorite = current_user.is_favorite(movie) if hasattr(current_user, 'is_favorite') else False

        if is_currently_favorite:
            current_user.remove_favorite(movie)
            action = "удален из"
            new_status = False
        else:
            current_user.add_favorite(movie)
            action = "добавлен в"
            new_status = True

        db.session.commit()
        flash(f'Фильм "{movie.title}" {action} избранное', 'success')

    except AttributeError as e:
        # Если у пользователя нет метода is_favorite
        flash('Ошибка: функция избранного недоступна. Пожалуйста, перезайдите в систему.', 'danger')
        return redirect(url_for('login'))
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при добавлении в избранное: {str(e)}', 'danger')

    return redirect(url_for('movie_detail', movie_id=movie_id))


@app.route('/favorites')
@login_required
def favorites():
    """Страница избранных фильмов"""
    page = request.args.get('page', 1, type=int)
    favorite_movies = current_user.favorite_movies.paginate(page=page, per_page=12)

    return render_template('favorites.html', favorite_movies=favorite_movies)


@app.route('/movie/add', methods=['GET', 'POST'])
@login_required
def add_movie():
    """Добавление фильма"""
    if not current_user.is_admin:
        abort(403)

    form = MovieForm()
    if form.validate_on_submit():
        movie = Movie(
            title=form.title.data,
            year=form.year.data,
            director=form.director.data,
            description=form.description.data,
            genre=form.genre.data
        )
        db.session.add(movie)
        db.session.commit()
        flash('Фильм добавлен!', 'success')
        return redirect(url_for('movie_detail', movie_id=movie.id))

    return render_template('movie_add.html', form=form)


@app.route('/movie/<int:movie_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_movie(movie_id):
    """Редактирование фильма"""
    if not current_user.is_admin:
        abort(403)

    movie = Movie.query.get_or_404(movie_id)
    form = MovieForm(obj=movie)

    if form.validate_on_submit():
        movie.title = form.title.data
        movie.year = form.year.data
        movie.director = form.director.data
        movie.description = form.description.data
        movie.genre = form.genre.data

        db.session.commit()
        flash('Фильм обновлен!', 'success')
        return redirect(url_for('movie_detail', movie_id=movie.id))

    return render_template('movie_add.html', form=form, movie=movie, title='Редактировать фильм')


@app.route('/movie/<int:movie_id>/delete', methods=['POST'])
@login_required
def delete_movie(movie_id):
    """Удаление фильма"""
    if not current_user.is_admin:
        abort(403)

    movie = Movie.query.get_or_404(movie_id)
    db.session.delete(movie)
    db.session.commit()
    flash('Фильм удален!', 'success')
    return redirect(url_for('movie_list'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Вход"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash('Вы успешно вошли!', 'success')
            return redirect(url_for('index'))
        flash('Неверное имя пользователя или пароль', 'danger')

    return render_template('login.html', form=form)


@app.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegisterForm()
    if form.validate_on_submit():
        # Проверяем, существует ли пользователь
        existing_user = User.query.filter_by(username=form.username.data).first()
        if existing_user:
            flash('Это имя пользователя уже занято', 'danger')
            return redirect(url_for('register'))

        user = User(username=form.username.data, email=form.email.data or None)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Регистрация успешна! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', form=form)


@app.route('/logout')
@login_required
def logout():
    """Выход"""
    logout_user()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('index'))


@app.route('/profile')
@login_required
def profile():
    """Профиль пользователя"""
    reviews = Review.query.filter_by(user_id=current_user.id).order_by(Review.created_at.desc()).limit(10).all()
    favorite_count = current_user.favorite_movies.count()

    return render_template('profile.html',
                           reviews=reviews,
                           favorite_count=favorite_count)


@app.route('/reinit-db')
@login_required
def reinit_db_route():
    """Пересоздание базы данных (только админ)"""
    if not current_user.is_admin:
        abort(403)

    # Удаляем все таблицы и создаем заново
    db.drop_all()
    db.create_all()

    # Инициализируем заново
    init_db()

    flash('База данных успешно пересоздана!', 'success')
    return redirect(url_for('index'))


@app.route('/admin/users')
@login_required
def admin_users():
    """Страница управления пользователями (только для админов)"""
    if not current_user.is_admin:
        abort(403)

    # Получаем всех пользователей
    users = User.query.order_by(User.created_at.desc()).all()

    # Статистика
    admin_count = User.query.filter_by(is_admin=True).count()
    regular_count = User.query.filter_by(is_admin=False).count()

    return render_template('admin/users.html',
                           users=users,
                           admin_count=admin_count,
                           regular_count=regular_count)


@app.route('/admin/user/<int:user_id>/make_admin', methods=['POST'])
@login_required
def make_admin(user_id):
    """Сделать пользователя администратором"""
    if not current_user.is_admin:
        abort(403)

    user = User.query.get_or_404(user_id)

    # Нельзя изменить свой статус
    if user.id == current_user.id:
        flash('Вы не можете изменить свой собственный статус', 'warning')
        return redirect(url_for('admin_users'))

    user.is_admin = True
    db.session.commit()

    flash(f'Пользователь {user.username} теперь администратор', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/remove_admin', methods=['POST'])
@login_required
def remove_admin(user_id):
    """Убрать права администратора"""
    if not current_user.is_admin:
        abort(403)

    user = User.query.get_or_404(user_id)

    # Нельзя изменить свой статус
    if user.id == current_user.id:
        flash('Вы не можете изменить свой собственный статус', 'warning')
        return redirect(url_for('admin_users'))

    user.is_admin = False
    db.session.commit()

    flash(f'Пользователь {user.username} больше не администратор', 'success')
    return redirect(url_for('admin_users'))


if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1', port=8080, debug=True)
