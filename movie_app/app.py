# app.py
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, NumberRange
from flask_restful import Api
from models import db, User, Movie, Review
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


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Веб-маршруты
@app.route('/')
def index():
    # Главная страница
    # Показываем топ фильмов и новые фильмы
    top_movies = Movie.query.order_by(Movie.rating.desc()).limit(6).all()
    new_movies = Movie.query.order_by(Movie.created_at.desc()).limit(6).all()

    # Только для админов показываем статистику
    movie_count = user_count = review_count = None
    if current_user.is_authenticated and current_user.is_admin:
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
    # Список всех фильмов
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
    # Страница фильма - доступна ВСЕМ пользователям
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
    # Добавить/удалить фильм из избранного
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
    # Страница избранных фильмов
    page = request.args.get('page', 1, type=int)
    favorite_movies = current_user.favorite_movies.paginate(page=page, per_page=12)

    return render_template('favorites.html', favorite_movies=favorite_movies)


@app.route('/movie/add', methods=['GET', 'POST'])
@login_required
def add_movie():
    # Добавление фильма
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
    # Редактирование фильма
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
    # Удаление фильма
    if not current_user.is_admin:
        abort(403)

    movie = Movie.query.get_or_404(movie_id)
    db.session.delete(movie)
    db.session.commit()
    flash('Фильм удален!', 'success')
    return redirect(url_for('movie_list'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    # Вход
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
    # Регистрация
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
    # Выход
    logout_user()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('index'))


@app.route('/profile')
@login_required
def profile():
    # Профиль пользователя
    reviews = Review.query.filter_by(user_id=current_user.id).order_by(Review.created_at.desc()).limit(10).all()
    favorite_count = current_user.favorite_movies.count()

    return render_template('profile.html',
                           reviews=reviews,
                           favorite_count=favorite_count)


@app.route('/reinit-db')
@login_required
def reinit_db_route():
    # Пересоздание базы данных (только админ)
    if not current_user.is_admin:
        abort(403)

    # Удаляем все таблицы и создаем заново
    db.drop_all()
    db.create_all()

    # Инициализируем заново
    from init_db import init_db
    init_db(app)

    flash('База данных успешно пересоздана!', 'success')
    return redirect(url_for('index'))


@app.route('/admin/users')
@login_required
def admin_users():
    # Страница управления пользователями (только для админов)
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
    # Сделать пользователя администратором
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
    # Убрать права администратора
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
    from init_db import init_db

    init_db(app)

    # Импортируем REST API после создания приложения
    from rest_api import register_api_resources

    register_api_resources(api)

    app.run(host='127.0.0.1', port=8080, debug=True)