"""
This module handles all Kafka-related operations for the application.

It provides utility functions to create Kafka producers, consumers, and to ensure
that the necessary topics exist before the application starts processing tasks.
The functions include retry logic to handle initial connection failures to the
Kafka broker, making the system more resilient.
"""
import json
import time
from kafka import KafkaProducer, KafkaConsumer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import NoBrokersAvailable

from . import config


def get_kafka_producer():
    """
    Initializes and returns a Kafka producer with retry logic.

    The producer is configured to serialize message values as JSON. It will
    indefinitely try to connect to the Kafka bootstrap servers until it
    succeeds.

    Returns:
        kafka.KafkaProducer: An initialized Kafka producer instance.
    """
    while True:
        try:
            producer = KafkaProducer(
                bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            print("Kafka producer connected.")
            return producer
        except NoBrokersAvailable as e:
            print(f"Failed to connect to Kafka producer, retrying... Error: {e}")
            time.sleep(5)


def get_kafka_consumer(topic):
    """
    Initializes and returns a Kafka consumer for a given topic with retry logic.

    The consumer is configured to deserialize JSON message values. It will
    indefinitely try to connect to the Kafka bootstrap servers until it
    succeeds.

    Args:
        topic (str): The Kafka topic to which the consumer will subscribe.

    Returns:
        kafka.KafkaConsumer: An initialized Kafka consumer instance.
    """
    while True:
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
                auto_offset_reset='earliest',
                value_deserializer=lambda v: json.loads(v.decode('utf-8'))
            )
            print(f"Kafka consumer for topic '{topic}' connected.")
            return consumer
        except NoBrokersAvailable as e:
            print(f"Failed to connect to Kafka consumer for topic '{topic}', retrying... Error: {e}")
            time.sleep(5)


def create_kafka_topics():
    """
    Creates the necessary Kafka topics if they do not already exist.

    Connects to the Kafka cluster as an admin and checks for the existence of
    the topics defined in the application's configuration. Any missing topics
    are created with a single partition and a replication factor of one.
    Includes retry logic for the admin client connection.
    """
    while True:
        try:
            admin_client = KafkaAdminClient(
                bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
                client_id='rag-app-admin'
            )

            existing_topics = admin_client.list_topics()
            topic_list = []
            for topic_name in config.TOPICS:
                if topic_name not in existing_topics:
                    partitions = 4 if topic_name in [config.KAFKA_QUERY_TOPIC, config.KAFKA_ARTICLE_TOPIC] else 1
                    topic_list.append(NewTopic(name=topic_name, num_partitions=partitions, replication_factor=1))

            if topic_list:
                admin_client.create_topics(new_topics=topic_list, validate_only=False)
                print(f"Created topics: {[t.name for t in topic_list]}")
            else:
                print("All topics already exist.")

            return
        except NoBrokersAvailable as e:
            print(f"Failed to create Kafka topics, retrying... Error: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"An unexpected error occurred while creating topics: {e}")
            time.sleep(5)
