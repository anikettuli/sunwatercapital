import sqlalchemy
from sqlalchemy import create_engine, Table, Column, Integer, String, MetaData, Text
from sqlalchemy.orm import sessionmaker
import time

from . import config

def get_db_connection():
    """Establishes a connection to the database and returns the engine."""
    # For SQLite, the connection is file-based and doesn't require retries like a network DB.
    try:
        engine = create_engine(config.DATABASE_URL)
        print("Database connection successful.")
        return engine
    except sqlalchemy.exc.SQLAlchemyError as e:
        print(f"Database connection failed. Error: {e}")
        # Exit or handle error appropriately if DB connection is critical at start
        raise


def setup_database(engine):
    """Sets up the database schema."""
    meta = MetaData()
    
    tasks = Table(
       'tasks', meta, 
       Column('id', Integer, primary_key=True), 
       Column('bill_id', String),
       Column('question_id', Integer),
       Column('status', String, default='pending'), # pending, completed, failed
       Column('answer', Text, nullable=True),
    )
    
    meta.create_all(engine)
    print("Database tables created or already exist.")
    return tasks

def get_session(engine):
    """Returns a new database session."""
    Session = sessionmaker(bind=engine)
    return Session()

class DBManager:
    def __init__(self, db_url=None):
        if db_url is None:
            db_url = config.DATABASE_URL
        self.engine = create_engine(db_url)
        self.meta = MetaData()
        self.tasks = self._define_tasks_table()
        self.meta.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def _define_tasks_table(self):
        return Table(
           'tasks', self.meta, 
           Column('id', Integer, primary_key=True), 
           Column('bill_id', String),
           Column('question_id', Integer),
           Column('status', String, default='pending'), # pending, completed, failed
           Column('answer', Text, nullable=True),
        )

    def get_session(self):
        return self.Session()

    def store_answer(self, bill_id, question_id, question, answer):
        session = self.get_session()
        try:
            # Check if a task entry already exists
            existing_task = session.query(self.tasks).filter_by(bill_id=bill_id, question_id=question_id).first()
            if existing_task:
                session.query(self.tasks).filter_by(bill_id=bill_id, question_id=question_id).update({
                    "answer": answer
                })
            else:
                ins = self.tasks.insert().values(
                    bill_id=bill_id,
                    question_id=question_id,
                    status='pending',
                    answer=answer
                )
                session.execute(ins)
            session.commit()
        except Exception as e:
            session.rollback()
            print(f"Error saving task to DB: {e}")
        finally:
            session.close()

    def mark_answer_complete(self, bill_id, question_id):
        session = self.get_session()
        try:
            session.query(self.tasks).filter_by(bill_id=bill_id, question_id=question_id).update({
                "status": "completed"
            })
            session.commit()
        except Exception as e:
            session.rollback()
            print(f"Error updating task status in DB: {e}")
        finally:
            session.close()

    def are_all_questions_answered(self, bill_id):
        session = self.get_session()
        try:
            completed_count = session.query(self.tasks).filter_by(bill_id=bill_id, status='completed').count()
            return completed_count == len(config.QUESTIONS)
        finally:
            session.close()

    def get_answers_for_bill(self, bill_id):
        session = self.get_session()
        try:
            results = session.query(self.tasks).filter_by(bill_id=bill_id).all()
            return {res.question_id: res.answer for res in results}
        finally:
            session.close()

db_manager = DBManager()
