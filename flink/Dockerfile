FROM flink:1.20-scala_2.12-java11

USER root

# Install Python and JDK headers (pyjnius needs JDK include/ on arm64)
RUN apt-get update -y && \
    apt-get install -y python3 python3-pip python3-dev default-jdk-headless && \
    rm -rf /var/lib/apt/lists/*
RUN ln -s /usr/bin/python3 /usr/bin/python

# Install PyFlink — set JAVA_HOME to the full JDK for pyjnius build,
# then Flink runtime will use its own JRE at /opt/java/openjdk
RUN JAVA_HOME=$(dirname $(dirname $(readlink -f $(which javac)))) \
    pip3 install --break-system-packages apache-flink==1.20.0

# Quantum simulation libraries (used by Flink UDFs for BB84 quantum state computation)
# --no-cache-dir avoids hash-mismatch errors from stale pip cache in base image
RUN pip3 install --break-system-packages --no-cache-dir \
    qiskit==1.3.2 \
    "numpy==1.26.4"

# Download connector JARs (3.x series for Flink 1.20)
RUN cd /opt/flink/lib && \
    curl -LO https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.3.0-1.20/flink-sql-connector-kafka-3.3.0-1.20.jar && \
    curl -LO https://repo1.maven.org/maven2/org/apache/flink/flink-connector-jdbc/3.2.0-1.19/flink-connector-jdbc-3.2.0-1.19.jar && \
    curl -LO https://jdbc.postgresql.org/download/postgresql-42.7.4.jar

USER flink
