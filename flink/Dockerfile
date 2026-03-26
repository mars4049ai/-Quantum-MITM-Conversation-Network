FROM flink:2.2.0

USER root

# Install Python and JDK headers (pyjnius needs JDK include/ on arm64)
RUN apt-get update -y && \
    apt-get install -y python3 python3-pip python3-dev default-jdk-headless && \
    rm -rf /var/lib/apt/lists/*
RUN ln -s /usr/bin/python3 /usr/bin/python

# Install PyFlink — set JAVA_HOME to the full JDK for pyjnius build,
# then Flink runtime will use its own JRE at /opt/java/openjdk
RUN JAVA_HOME=$(dirname $(dirname $(readlink -f $(which javac)))) \
    pip3 install --break-system-packages apache-flink==2.2.0

# Quantum simulation libraries (used by Flink UDFs for BB84 quantum state computation)
RUN pip3 install --break-system-packages \
    qiskit==1.4.2 \
    qiskit-aer==0.15.1 \
    numpy>=1.26

# Download connector JARs (4.x series for Flink 2.x)
RUN cd /opt/flink/lib && \
    curl -LO https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/4.0.1-2.0/flink-sql-connector-kafka-4.0.1-2.0.jar && \
    curl -LO https://repo1.maven.org/maven2/org/apache/flink/flink-connector-jdbc-core/4.0.0-2.0/flink-connector-jdbc-core-4.0.0-2.0.jar && \
    curl -LO https://repo1.maven.org/maven2/org/apache/flink/flink-connector-jdbc-postgres/4.0.0-2.0/flink-connector-jdbc-postgres-4.0.0-2.0.jar && \
    curl -LO https://jdbc.postgresql.org/download/postgresql-42.7.4.jar

USER flink
