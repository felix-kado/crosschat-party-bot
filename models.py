from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Table
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

# Table for the many-to-many relationship between users and chats
user_chat_association = Table('user_chat_association', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.user_id')),
    Column('chat_id', Integer, ForeignKey('chats.chat_id'))
)

# Table for the many-to-many relationship between users and parties
user_party_association = Table('user_party_association', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.user_id')),
    Column('party_id', Integer, ForeignKey('parties.party_id'))
)

class User(Base):
    __tablename__ = 'users'

    user_id = Column(Integer, primary_key=True)
    name = Column(String)
    chats = relationship('Chat', secondary=user_chat_association, back_populates='members')
    notified_parties = relationship('Party', secondary=user_party_association, back_populates='notified')

class Chat(Base):
    __tablename__ = 'chats'

    chat_id = Column(Integer, primary_key=True)
    name = Column(String)
    members = relationship('User', secondary=user_chat_association, back_populates='chats')

class Party(Base):
    __tablename__ = 'parties'

    party_id = Column(Integer, primary_key=True)
    description = Column(String)
    poll_message_id = Column(Integer)
    poll_chat_id = Column(Integer)
    notified = relationship('User', secondary=user_party_association, back_populates='notified_parties', primaryjoin=user_party_association.c.party_id == party_id)

# create engine
engine = create_engine('sqlite:///parties_poll.db')
Base.metadata.create_all(engine)

# create session
Session = sessionmaker(bind=engine)
session = Session()
