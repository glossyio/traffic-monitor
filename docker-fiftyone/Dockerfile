#not currently used on the RPi, but here for reference
# from https://github.com/Data-drone/fiftyone_app/
FROM datadrone/deeplearn_minimal:cuda-11.1-base

USER root

RUN apt-get update && \
    apt-get install -y libcurl4

COPY startserver.py /opt/startserver.py
RUN chown $NB_USER:1000 /opt/startserver.py

USER $NB_USER



RUN pip install fiftyone

CMD ["python", "/opt/startserver.py"]