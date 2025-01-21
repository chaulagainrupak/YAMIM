import json
import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
import sys
from datetime import datetime

import requests
# Initialize Flask app
app = Flask(__name__)
app.secret_key = "supersecretkey"

# Define config file path
configFile = "config.json"
launcherProfilesFile = "launcher_profiles.json"

# Determine OS
osType = sys.platform

# URLS
mojangAPI = "https://launchermeta.mojang.com/mc/game/version_manifest.json"

if osType.lower() == 'win32':
    defaultDir = os.path.join(os.getenv('APPDATA'), "Minecraft")
elif osType.lower() == 'linux':
    defaultDir = os.path.expanduser("~/.minecraft")
else:
    defaultDir = ""


def changeGameDir(path):
    # Update only the gameDir in the configuration file
    try:
        with open(configFile, "r") as config:
            configData = json.load(config)
    except (FileNotFoundError, json.JSONDecodeError):
        configData = {}  # Default to empty dict if file doesn't exist or is corrupted

    configData["gameDir"] = path
    createYamim(path)

    with open(configFile, "w") as config:
        json.dump(configData, config, indent=4)


def createYamim(path):
    if os.path.exists(path) and not os.path.exists(os.path.join(path, "YAMIM")):
        os.mkdir(os.path.join(path, "YAMIM"))


def getInstanceData(instancePath):
    """
    Fetches the mods and resource packs data from an instance directory.
    Returns a dictionary with the mod names and their corresponding file names,
    and a list of resource packs.
    """
    mods = {}
    resourcePacks = []

    modsPath = os.path.join(instancePath, "mods")
    resourcePacksPath = os.path.join(instancePath, "resourcepacks")

    if os.path.exists(modsPath):
        for modFile in os.listdir(modsPath):
            if modFile.endswith(".jar"):  # Assuming mods are .jar files
                modName = os.path.splitext(modFile)[0]
                mods[modName] = modFile

    if os.path.exists(resourcePacksPath):
        resourcePacks = [rp for rp in os.listdir(resourcePacksPath) if os.path.isdir(os.path.join(resourcePacksPath, rp))]

    return mods, resourcePacks


def getInstanceCreationDate(instancePath):
    """
    Get the creation date of an instance directory.
    """
    return datetime.fromtimestamp(os.path.getctime(instancePath)).isoformat()


def getLatestPlayedInstance():
    """
    Fetches the latest played instance from the launcher_profiles.json file.
    Returns the instance name or None if no profile is found.
    """
    if os.path.exists(launcherProfilesFile):
        try:
            with open(launcherProfilesFile, "r") as file:
                profiles = json.load(file)
                selectedProfile = profiles.get("selectedProfile")
                if selectedProfile:
                    return selectedProfile["name"]
        except json.JSONDecodeError:
            return None
    return None


# Initialize config.json if it does not exist
if os.path.exists(configFile):
    # Load the configuration if the file exists
    with open(configFile, "r") as config:
        try:
            configData = json.load(config)
            gameDir = configData.get("gameDir")

            # Use the directory only if it's not None and exists
            if gameDir and os.path.exists(gameDir):
                createYamim(gameDir)
            elif os.path.exists(defaultDir):
                createYamim(defaultDir)
                changeGameDir(defaultDir)

        except json.JSONDecodeError:
            # Handle invalid JSON format by resetting to default
            gameDir = defaultDir
else:
    # Create a default configuration if the file does not exist
    defaultConfig = {"gameDir": None, "instances": []}
    with open(configFile, "w") as config:
        json.dump(defaultConfig, config, indent=4)
    gameDir = defaultDir


@app.route("/")
def index():
    message = requests.get(mojangAPI).json()
    versions = message['versions']

    with open(configFile, "r") as config:
        try:
            configData = json.load(config)
            instances = configData.get("instances", [])

            # Check for instances that are not in the config
            if gameDir:
                yamimPath = os.path.join(gameDir, "YAMIM")
                if os.path.exists(yamimPath):
                    instanceDirs = os.listdir(yamimPath)

                    # Add missing instances to the config
                    for instanceName in instanceDirs:
                        instancePath = os.path.join(yamimPath, instanceName)
                        if os.path.isdir(instancePath) and not any(instance["name"] == instanceName for instance in instances):
                            # Get mod and resource pack info
                            mods, resourcePacks = getInstanceData(instancePath)
                            creationDate = getInstanceCreationDate(instancePath)

                            newInstance = {
                                "name": instanceName,
                                "version": "unknown",  # We will set this as unknown for now
                                "loader": "unknown",   # You may want to set loader manually
                                "enabledMods": list(mods.keys()), 
                                "disabledMods": [],    # Empty by default
                                "resourcePacks": resourcePacks,
                                "createdAt": creationDate
                            }
                            instances.append(newInstance)

                    # Remove instances from the config if their directories are missing
                    instancesToRemove = [instance for instance in instances if not os.path.exists(os.path.join(yamimPath, instance["name"]))]
                    for instance in instancesToRemove:
                        instances.remove(instance)

                    # Save the updated config
                    with open(configFile, "w") as f:
                        json.dump(configData, f, indent=4)

            # Sort instances by latest played instance (from launcher_profiles.json)
            latestPlayedInstance = getLatestPlayedInstance()
            if latestPlayedInstance:
                instances.sort(key=lambda x: (x["name"] != latestPlayedInstance, x["createdAt"]), reverse=True)

        except json.JSONDecodeError:
            instances = []

    return render_template("index.html", gameDir=gameDir, latest=message, versions=versions, instances=instances)


@app.route("/updateDefaultDir", methods=["POST"])
def updateDefaultDir():
    newDir = request.get_json().get("newDir")

    # Expand ~ for Linux if necessary
    if osType.lower() == "linux" and "~" in newDir:
        newDir = os.path.expanduser(newDir)

    if os.path.exists(newDir):
        defaultDir = newDir
        changeGameDir(defaultDir)
        return jsonify({"response": "success"}), 200
    else:
        defaultDir = None
        changeGameDir(None)
        return jsonify({"response": "directory doesn't exist"}), 304


@app.route("/createInstance", methods=["POST"])
def createInstance():
    instanceName = request.form.get("name")
    version = request.form.get("version")
    loader = "fabric"  # Currently fixed to "fabric"

    # Validate inputs
    if not instanceName or not version:
        flash("Instance name and version are required.", "error")
        return redirect(url_for("index"))

    if not instanceName.isalnum():
        flash("Instance name must only contain letters and numbers.", "error")
        return redirect(url_for("index"))

    if not gameDir or not os.path.exists(gameDir):
        flash("Game directory is not configured or doesn't exist.", "error")
        return redirect(url_for("index"))

    # Construct paths
    instancePath = os.path.join(gameDir, "YAMIM", instanceName)
    modsPath = os.path.join(instancePath, "mods")
    disabledModsPath = os.path.join(modsPath, "disabled")  # Disabled mods inside mods folder
    resourcePacksPath = os.path.join(instancePath, "resourcepacks")

    try:
        # Create directories
        os.makedirs(modsPath)  # Creates the mods directory
        os.makedirs(disabledModsPath)  # Disabled mods inside the mods directory
        os.mkdir(resourcePacksPath)  # Directory for resource packs

        # Add instance details to the config file
        with open(configFile, "r") as f:
            config = json.load(f)

        # Ensure "instances" key exists in the config
        if "instances" not in config:
            config["instances"] = []

        # Check if instance already exists in the config
        if any(instance["name"] == instanceName for instance in config["instances"]):
            flash(f"The instance '{instanceName}' already exists in the config.", "error")
            return redirect(url_for("index"))

        # Add the new instance details
        newInstance = {
            "name": instanceName,
            "version": version,
            "loader": loader,
            "enabledMods": [],
            "disabledMods": [],
            "resourcePacks": [],
            "createdAt": datetime.now().isoformat()
        }
        config["instances"].append(newInstance)

        # Save the updated config without overwriting unrelated data
        with open(configFile, "w") as f:
            json.dump(config, f, indent=4)

        flash(f"Instance '{instanceName}' created successfully!", "success")
        return redirect(url_for("index"))

    except FileExistsError:
        flash(f"The instance '{instanceName}' already exists in the filesystem.", "error")
        return redirect(url_for("index"))

    except Exception as e:
        flash(f"An unexpected error occurred: {str(e)}", "error")
        return redirect(url_for("index"))


@app.route("/editInstance/<instance_name>", methods=["GET", "POST"])
def editInstance(instance_name):
    try:
        with open(configFile, "r") as f:
            config = json.load(f)
        
        # Find the instance to edit
        instanceToEdit = next((instance for instance in config["instances"] if instance["name"] == instance_name), None)

        if not instanceToEdit:
            flash(f"Instance '{instance_name}' not found.", "error")
            return redirect(url_for("index"))

        if request.method == "POST":            
            # Handling mod installation or removal
            if "modName" in request.form:
                modName = request.form["modName"]
                instanceToEdit["enabledMods"].append(modName)  # You can modify this based on how you want to handle mods
            
            # Handling resource pack installation or removal
            if "resourcePackName" in request.form:
                resourcePackName = request.form["resourcePackName"]
                instanceToEdit["resourcePacks"].append(resourcePackName)  # Modify as needed

            # Save the updated instance data
            with open(configFile, "w") as f:
                json.dump(config, f, indent=4)

            flash(f"Instance '{instance_name}' updated successfully!", "success")
            return redirect(url_for("editInstance", instance_name=instance_name))

        return render_template("edit_instance.html", instance=instanceToEdit)

    except Exception as e:
        flash(f"An error occurred while editing the instance: {str(e)}", "error")
        return redirect(url_for("index"))



@app.route("/deleteInstance/<instance_name>", methods=["POST"])
def deleteInstance(instance_name):
    """
    Deletes the specified instance from the config and filesystem.
    """
    try:
        with open(configFile, "r") as f:
            config = json.load(f)

        # Find and remove the instance from the config
        instanceToDelete = next((instance for instance in config["instances"] if instance["name"] == instance_name), None)
        if instanceToDelete:
            config["instances"].remove(instanceToDelete)
            # Delete the instance directory from the filesystem
            instanceDirPath = os.path.join(gameDir, "YAMIM", instance_name)
            if os.path.exists(instanceDirPath):
                for root, dirs, files in os.walk(instanceDirPath, topdown=False):
                    for file in files:
                        os.remove(os.path.join(root, file))
                    for dir in dirs:
                        os.rmdir(os.path.join(root, dir))
                os.rmdir(instanceDirPath)
            # Save the updated config
            with open(configFile, "w") as f:
                json.dump(config, f, indent=4)

            flash(f"Instance '{instance_name}' deleted successfully!", "success")
        else:
            flash(f"Instance '{instance_name}' not found.", "error")
    except Exception as e:
        flash(f"An error occurred while deleting the instance: {str(e)}", "error")

    return redirect(url_for("index"))


@app.route("/searchModrinth", methods=["GET"])
def searchModrinth():
    query = request.args.get("query")
    if not query:
        return jsonify({"hits": []})
    
    # Request to Modrinth API
    url = f"https://api.modrinth.com/api/v1/search"
    params = {
        "query": query,
        "limit": 5,
        "facets": "categories:mod"
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return jsonify(response.json())
    return jsonify({"hits": []})


@app.route("/installMod/<mod_id>/<instance_name>", methods=["POST"])
def installMod(mod_id, instance_name):
    try:
        # Fetch basic mod details (title, icon, loaders)
        mod_details_url = f"https://api.modrinth.com/v2/project/{mod_id}"
        mod_details_response = requests.get(mod_details_url)
        if mod_details_response.status_code != 200:
            return jsonify({"status": "error", "message": "Failed to fetch mod details."})

        mod_details = mod_details_response.json()
        mod_name = mod_details["title"]
        mod_icon_url = mod_details.get("icon_url", "")
        mod_loaders = mod_details.get("categories", [])

        # Fetch mod version details
        mod_version_url = f"https://api.modrinth.com/v2/project/{mod_id}/version"
        mod_version_response = requests.get(mod_version_url)
        if mod_version_response.status_code != 200:
            return jsonify({"status": "error", "message": "Failed to fetch mod version details."})

        mod_versions = mod_version_response.json()

        # Load the config file
        with open(configFile, "r") as f:
            config = json.load(f)

        # Locate the instance
        instance = next((inst for inst in config["instances"] if inst["name"] == instance_name), None)
        if not instance:
            return jsonify({"status": "error", "message": f"Instance '{instance_name}' not found."})

        instance_version = instance["version"]
        instance_loader = instance["loader"]

        # Check for modloader compatibility
        if instance_loader not in mod_loaders:
            return jsonify({"status": "error", "message": f"Mod '{mod_name}' is not compatible with the '{instance_loader}' loader."})

        # Match mod's supported versions with the instance's version
        compatible_version = next(
            (version for version in mod_versions if instance_version in version["game_versions"]), None
        )
        if not compatible_version:
            return jsonify({"status": "error", "message": "No compatible version found for the instance."})

        # Get the mod file details
        file_details = compatible_version["files"][0]
        mod_url = file_details["url"]
        mod_filename = file_details["filename"]

        # Check if the mod is already in enabledMods
        if any(mod["modId"] == mod_id for mod in instance["enabledMods"]):
            return jsonify({"status": "info", "message": f"Mod '{mod_name}' is already installed."})

        # Prepare paths
        instance_dir = os.path.join(gameDir, "YAMIM", instance_name)
        mod_dir = os.path.join(instance_dir, "mods")
        os.makedirs(mod_dir, exist_ok=True)

        # Download the mod file
        mod_path = os.path.join(mod_dir, mod_filename)
        mod_response = requests.get(mod_url)
        if mod_response.status_code == 200:
            with open(mod_path, "wb") as f:
                f.write(mod_response.content)
        else:
            return jsonify({"status": "error", "message": "Failed to download the mod file."})

        # Add the mod to the enabledMods
        mod_entry = {
            "modId": mod_id,
            "modJar": mod_filename,
            "modName": mod_name,
            "modIcon": mod_icon_url
        }
        instance["enabledMods"].append(mod_entry)

        # Save the updated configuration
        with open(configFile, "w") as f:
            json.dump(config, f, indent=4)

        return jsonify({"status": "success", "message": f"Mod '{mod_name}' installed successfully!"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})



if __name__ == "__main__":
    app.run(debug=True)
