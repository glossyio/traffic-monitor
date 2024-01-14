#Zoo example load
# from https://github.com/Data-drone/fiftyone_app/
# import fiftyone as fo
# import fiftyone.zoo as foz


# dataset=foz.load_zoo_dataset("quickstart")
# session=fo.launch_app(dataset, port=8082)

# session.wait()


# default images for Buster
import fiftyone as fo

# Create a dataset from a directory of images
#datasetimg = fo.Dataset.from_images_dir("/fiftyone/clips")
dataset_img = fo.Dataset.from_dir(
    dataset_dir="/fiftyone/clips",
    dataset_type=fo.types.ImageDirectory,
    name="/fiftyone/clips",
)
#to save to database and keep metadata each reload
# should also save it off
#dataset_img.persistent = True

#datasetvid = fo.Dataset.from_videos_dir("/fiftyone/recordings")
datasetvid = fo.Dataset.from_dir(
    dataset_dir="/fiftyone/recordings",
    dataset_type=fo.types.VideoDirectory,
    name="/fiftyone/recordings",
)
#to save to database and keep metadata each reload
# should also save it off
#datasetvid.persistent = True

session = fo.launch_app()

session.wait()