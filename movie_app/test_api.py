import unittest
import tempfile
import os
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class MovieAPITestCase(unittest.TestCase):
    def setUp(self):
        # Временная БД - SQLite в памяти или временный файл
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')

        # Импортируем здесь чтобы избежать конфликтов с основной БД
        from app import app, db
        from models import User, Movie, Review

        self.app = app
        self.db = db
        self.User = User
        self.Movie = Movie
        self.Review = Review

        # Переопределяем конфигурацию для тестов
        self.app.config['TESTING'] = True
        self.app.config['DEBUG'] = False
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-testing'
        self.app.config['LOGIN_DISABLED'] = False

        self.client = self.app.test_client()

        with self.app.app_context():
            # Создаем все таблицы
            self.db.create_all()

            # Тестовый админ
            admin = self.User(username='testadmin', email='admin@test.com', is_admin=True)
            admin.set_password('admin123')
            self.db.session.add(admin)

            # Тестовый обычный пользователь
            user = self.User(username='testuser', email='user@test.com', is_admin=False)
            user.set_password('user123')
            self.db.session.add(user)

            # Тестовые фильмы
            movie1 = self.Movie(
                title='Test Movie 1',
                year=2024,
                director='Director 1',
                genre='Drama',
                description='Description 1'
            )
            movie2 = self.Movie(
                title='Test Movie 2',
                year=2023,
                director='Director 2',
                genre='Comedy',
                description='Description 2'
            )
            self.db.session.add(movie1)
            self.db.session.add(movie2)

            self.db.session.commit()

            self.admin_id = admin.id
            self.user_id = user.id
            self.movie1_id = movie1.id
            self.movie2_id = movie2.id

    def tearDown(self):
        """Очистка после каждого теста"""
        with self.app.app_context():
            # Удаляем все таблицы
            self.db.session.remove()
            self.db.drop_all()

        # Закрываем файловый дескриптор и удаляем временный файл
        os.close(self.db_fd)
        try:
            os.unlink(self.db_path)
        except:
            pass

    def login_as_user(self, user_id=None):
        """Авторизуем пользователя в тестовом контексте"""
        with self.app.app_context():
            if user_id == 'admin':
                user = self.User.query.filter_by(username='testadmin').first()
            elif user_id == 'user':
                user = self.User.query.filter_by(username='testuser').first()
            else:
                user = None

            if user:
                # Авторизуем через сессию
                with self.client.session_transaction() as sess:
                    sess['_user_id'] = str(user.id)
                    sess['_fresh'] = True
                return True
        return False

    # ========== ТЕСТЫ БЕЗ АВТОРИЗАЦИИ ==========

    def test_get_movies_without_auth(self):
        """Тест получения фильмов без авторизации"""
        response = self.client.get('/api/v1/movies/')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertEqual(len(data), 2)

    def test_get_single_movie_without_auth(self):
        """Тест получения одного фильма без авторизации"""
        response = self.client.get(f'/api/v1/movies/{self.movie1_id}')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertEqual(data['title'], 'Test Movie 1')

    def test_get_reviews_without_auth(self):
        """Тест получения отзывов без авторизации"""
        response = self.client.get(f'/api/v1/movies/{self.movie1_id}/reviews/')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertIsInstance(data, list)

    def test_create_movie_without_auth_forbidden(self):
        """Тест создания фильма без авторизации"""
        response = self.client.post('/api/v1/movies/', json={
            'title': 'New Movie',
            'year': 2025,
            'director': 'Director'
        }, follow_redirects=False)

        # Flask-Login возвращает 302 редирект на логин
        self.assertEqual(response.status_code, 302)

    def test_create_review_without_auth_forbidden(self):
        """Тест создания отзыва без авторизации"""
        response = self.client.post(f'/api/v1/movies/{self.movie1_id}/reviews/', json={
            'content': 'Great movie!',
            'rating': 5
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 302)

    # ========== ТЕСТЫ С АВТОРИЗАЦИЕЙ ПОЛЬЗОВАТЕЛЯ ==========

    def test_create_review_as_user(self):
        """Тест создания отзыва обычным пользователем"""
        self.login_as_user('user')

        response = self.client.post(f'/api/v1/movies/{self.movie1_id}/reviews/',
                                    json={'content': 'Very good movie!', 'rating': 5})

        self.assertEqual(response.status_code, 201)

        data = json.loads(response.data)
        self.assertEqual(data['content'], 'Very good movie!')
        self.assertEqual(data['rating'], 5)

    def test_create_movie_as_user_forbidden(self):
        """Тест создания фильма обычным пользователем"""
        self.login_as_user('user')

        response = self.client.post('/api/v1/movies/',
                                    json={'title': 'New Movie', 'year': 2025, 'director': 'User'})

        self.assertEqual(response.status_code, 403)

    def test_add_to_favorites_as_user(self):
        """Тест добавления в избранное обычным пользователем"""
        self.login_as_user('user')

        response = self.client.post(f'/api/v1/movies/{self.movie1_id}/favorite/')
        # Может быть 201 или 200
        self.assertIn(response.status_code, [200, 201])

    def test_remove_from_favorites_as_user(self):
        """Тест удаления из избранного обычным пользователем"""
        self.login_as_user('user')

        # Сначала добавляем
        self.client.post(f'/api/v1/movies/{self.movie1_id}/favorite/')

        # Потом удаляем
        response = self.client.delete(f'/api/v1/movies/{self.movie1_id}/favorite/')
        self.assertIn(response.status_code, [200, 204])

    # ========== ТЕСТЫ С АВТОРИЗАЦИЕЙ АДМИНА ==========

    def test_create_movie_as_admin(self):
        """Тест создания фильма администратором"""
        self.login_as_user('admin')

        response = self.client.post('/api/v1/movies/',
                                    json={
                                        'title': 'New Movie from Admin',
                                        'year': 2025,
                                        'director': 'Admin Director'
                                    })

        self.assertEqual(response.status_code, 201)

        data = json.loads(response.data)
        self.assertEqual(data['title'], 'New Movie from Admin')

    def test_update_movie_as_admin(self):
        """Тест обновления фильма администратором"""
        self.login_as_user('admin')

        response = self.client.put(f'/api/v1/movies/{self.movie1_id}',
                                   json={
                                       'title': 'Updated Movie',
                                       'year': 2024,
                                       'director': 'Updated Director'
                                   })

        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertEqual(data['title'], 'Updated Movie')

    def test_delete_movie_as_admin(self):
        """Тест удаления фильма администратором"""
        self.login_as_user('admin')

        response = self.client.delete(f'/api/v1/movies/{self.movie1_id}')
        self.assertEqual(response.status_code, 200)

        # Проверяем, что фильм действительно удален
        response = self.client.get(f'/api/v1/movies/{self.movie1_id}')
        self.assertEqual(response.status_code, 404)

    # ========== БАЗОВЫЕ ТЕСТЫ ==========

    def test_database_operations(self):
        """Тест операций с базой данных"""
        with self.app.app_context():
            users = self.User.query.all()
            self.assertEqual(len(users), 2)

            movies = self.Movie.query.all()
            self.assertEqual(len(movies), 2)

            reviews = self.Review.query.all()
            self.assertEqual(len(reviews), 0)


# Простые тесты веб-интерфейса (без не-ASCII символов в байтовых строках)
class WebInterfaceTestCase(unittest.TestCase):
    def setUp(self):
        # Временная БД в памяти для веб-тестов
        from app import app, db
        from models import User, Movie

        self.app = app
        self.db = db
        self.User = User
        self.Movie = Movie

        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key'

        self.client = self.app.test_client()

        with self.app.app_context():
            self.db.create_all()

            # Создаем тестового пользователя
            user = self.User(username='testuser', email='test@test.com')
            user.set_password('test123')
            self.db.session.add(user)

            # Создаем тестовый фильм
            movie = self.Movie(
                title='Test Web Movie',
                year=2024,
                director='Web Director',
                genre='Web Genre'
            )
            self.db.session.add(movie)

            self.db.session.commit()

            self.user_id = user.id
            self.movie_id = movie.id

    def tearDown(self):
        with self.app.app_context():
            self.db.session.remove()
            self.db.drop_all()

    def test_home_page(self):
        """Тест главной страницы"""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        # Используем обычную строку вместо байтовой
        response_text = response.get_data(as_text=True)
        self.assertIn('html', response_text)  # Проверяем что это HTML
        self.assertIn('body', response_text)

    def test_movies_page(self):
        """Тест страницы со списком фильмов"""
        response = self.client.get('/movies')
        self.assertEqual(response.status_code, 200)
        response_text = response.get_data(as_text=True)
        self.assertIn('Test Web Movie', response_text)

    def test_movie_detail_page(self):
        """Тест страницы фильма"""
        response = self.client.get(f'/movie/{self.movie_id}')
        self.assertEqual(response.status_code, 200)
        response_text = response.get_data(as_text=True)
        self.assertIn('Test Web Movie', response_text)


# Тесты API с русскими символами (используем правильное кодирование)
class RussianAPITestCase(unittest.TestCase):
    def setUp(self):
        from app import app, db
        from models import User, Movie

        self.app = app
        self.db = db
        self.User = User
        self.Movie = Movie

        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key'

        self.client = self.app.test_client()

        with self.app.app_context():
            self.db.create_all()

            # Создаем тестового пользователя с русским именем
            user = self.User(username='test_user')
            user.set_password('test123')
            self.db.session.add(user)

            # Создаем тестовый фильм с русским названием
            movie = self.Movie(
                title='Тестовый фильм',
                year=2024,
                director='Тестовый режиссер'
            )
            self.db.session.add(movie)

            self.db.session.commit()

            self.movie_id = movie.id

    def tearDown(self):
        with self.app.app_context():
            self.db.session.remove()
            self.db.drop_all()

    def test_russian_movie_title(self):
        """Тест с русскими символами в JSON"""
        response = self.client.get(f'/api/v1/movies/{self.movie_id}')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertEqual(data['title'], 'Тестовый фильм')

    def test_russian_content_in_review(self):
        """Тест создания отзыва с русским текстом"""
        # Логинимся через сессию
        with self.app.app_context():
            user = self.User.query.first()
            with self.client.session_transaction() as sess:
                sess['_user_id'] = str(user.id)

        response = self.client.post(f'/api/v1/movies/{self.movie_id}/reviews/',
                                    json={
                                        'content': 'Отличный фильм!',
                                        'rating': 5
                                    })

        self.assertEqual(response.status_code, 201)

        data = json.loads(response.data)
        self.assertEqual(data['content'], 'Отличный фильм!')


# Простые тесты с временной базой данных
class SimpleAPITests(unittest.TestCase):
    """Простые тесты с временной БД"""

    def setUp(self):
        # Создаем временную БД в памяти
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')

        from app import app, db
        from models import User, Movie

        self.app = app
        self.db = db
        self.User = User
        self.Movie = Movie

        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key'

        self.client = self.app.test_client()

        # Создаем таблицы и минимальные данные
        with self.app.app_context():
            self.db.create_all()

            # Создаем один фильм для тестов
            movie = self.Movie(
                title='Simple Test Movie',
                year=2024,
                director='Test Director'
            )
            self.db.session.add(movie)
            self.db.session.commit()

            self.movie_id = movie.id

    def tearDown(self):
        with self.app.app_context():
            self.db.session.remove()
            self.db.drop_all()

        os.close(self.db_fd)
        try:
            os.unlink(self.db_path)
        except:
            pass

    def test_api_endpoints_exist(self):
        """Тест что основные API endpoints существуют"""
        # Проверяем что можем получить фильмы
        response = self.client.get('/api/v1/movies/')
        self.assertIn(response.status_code, [200, 302])

        # Проверяем что можем получить конкретный фильм
        response = self.client.get(f'/api/v1/movies/{self.movie_id}')
        self.assertIn(response.status_code, [200, 302])

    def test_web_pages_exist(self):
        """Тест что веб-страницы существуют"""
        pages = [
            '/',
            '/movies',
            '/login',
            '/register',
            f'/movie/{self.movie_id}'
        ]

        for page in pages:
            response = self.client.get(page)
            # Проверяем что не 404 (могут быть 200, 302 и т.д.)
            self.assertNotEqual(response.status_code, 404,
                                f"Страница {page} возвращает 404")


if __name__ == '__main__':
    # Запускаем тесты
    unittest.main(verbosity=2)