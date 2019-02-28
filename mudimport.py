'''
Module that deserializes developer-made game-data, converting it into real objects
'''
import json
import os
import importlib
import traceback
from location import Location, Exit
from util.stocstring import StocString
from util.distr import RandDist

def get_filenames(directory, ext=""):
    '''returns all filenames in [directory] with extension [ext]'''
    return [directory + name for name in os.listdir(directory) \
            if name.endswith(ext)]

class Library:
    '''Class to represent a library of interacting game elements'''
    def __init__(self):
        self.locations = {}
        self.char_classes = {}
        self.items = {}
        # random distribution based on class frequencies
        self.random_class = None
        self._loc_importer = LocationImporter(self.locations)
        self._char_importer = CharacterClassImporter(self.char_classes)
        self._item_importer = ItemImporter(self.items)

    def build_class_distr(self):
        '''takes the current set of CharacterClasses
        and builds a random distribution based on their frequency
        can be called again to rebuild the distribution
        '''
        # grab character classes with frequency > 0
        to_include = [c_class for c_class in self.char_classes.values() 
                     if c_class.frequency > 0]
        if len(to_include) == 0:
            raise Exception("No valid classes with frequency greater than 0")
        self.random_class = RandDist(to_include, list(map(lambda x: x.frequency, to_include)))
    
    def import_files(self, locations=[], chars=[], items=[]):
        if locations:
            for filename in locations:
                self._loc_importer.import_file(filename)
        if chars:
            for filename in chars:
                self._char_importer.import_file(filename, locations=self.locations)
        if items:
            for filename in items:
                self._item_importer.import_file(filename)
        if locations:
            self._loc_importer.build_exits(*self.locations.keys())
            #self._loc_importer.add_items()
            #self._loc_importer.add_entities()
    
    def import_results(self):
        return str(self._loc_importer) + str(self._item_importer) + str(self._char_importer)
    
    def __repr__(self):
        output = []
        if self.locations:
            output += ["Locations:    " + repr(list(self.locations.keys()))]
        if self.char_classes:
            output += ["CharClasses:  " + repr(list(self.char_classes.keys()))]
        if self.items:
            output += ["Items:        " + repr(list(self.items.keys()))]
        return "\n".join(output)
        


# see if this trashes the stack trace
class ImporterException(Exception):
    def __init__(self, message, game_element):
        self.game_element = game_element
        super().__init__(message)

def process_json(filename):
    with open(filename) as location_file:
        # read the file, processing any stocstring macros
        json_data = StocString.process(location_file.read())
    json_data = json.loads(json_data)
    # all importers expect a "name" field, so check for that
    assert("name" in json_data and type(json_data["name"]) is str)
    return json_data

class Importer:
    '''Base class for other importers
    objects:        dict mapping object names -> object instances
    object_source:  dict mapping object names -> filenames
    file_data:      dict mapping filenames -> filedata
    file_fails:     dict mapping filenames -> reasons while file failed to load
    failures:       dict mapping object names -> reasons why they could not be constructed
    '''
    def __init__(self, lib={}):
        self.objects = lib
        self.object_source = {}
        self.file_data = {}
        self.file_fails = {}
        self.failures = {}
    
    def import_file(self, filename, **kwargs):
        '''Import one file with filename [filename]'''
        try:
            json_data = process_json(filename)
            self.file_data[filename] = json_data
        except Exception as ex:
            self.file_fails[filename] = traceback.format_exc()
            return
        try:
            name, game_object = self._do_import(json_data, **kwargs)
            self.objects[name] = game_object
            self.object_source[name] = filename
        except Exception as ex:
            self.failures[ex.name] = traceback.format_exc()

    def _do_import(self, json_data):
        '''This method should be implemented in base classes
        _do_import should return a tuple:
            (name, object)
        where name is the name of the object
        a file created by _do_import should be guaranteed to
        have proper syntax, type checking, etc.
        '''
        pass

    def __repr__(self):
        '''cheap method to get an output for all values in each list'''
        output = [repr(self.__class__)]
        output += ["Successes:       " + repr(self.objects.keys())]
        output += ["File Failures:   " + repr(self.file_fails.keys())]
        output += ["Build Failures:  " + repr(self.failures.keys())]
        return "\n".join(output)

    def __str__(self):
        output = []
        if self.objects:
            output.append("\tSuccesses [%s]" % len(self.objects))
            for success in self.objects:
                output.append(success)
        else:
            output.append("\t[No Successes]")
        if self.file_fails:
            output.append("\tFile Failures [%s]" % len(self.file_fails))
            for fail_name, fail in self.file_fails.items():
                output.append(fail_name)
                output.append(fail)
        else:
            output.append("\t[No File Failures]")
        if self.failures:
            output.append("\tBuild Failures [%s]" % len(self.failures))
            for fail_name, fail in self.failures.items():
                output.append(fail_name)
                output.append(fail)
        else:
            output.append("\t[No Build Failures]")
        return "\n".join(output)
        

class LocationImporter(Importer):
    '''Imports Locations from json'''
    def __init__(self, lib={}):
        '''
        exit_failure: dict mapping destination names to a dict:
        {"reason" : [reason for failure], "affected": [names of locations affected]}
        '''
        self.exit_failures = {}
        super().__init__(lib)

    def _do_import(self, json_data):
        try:
            name = json_data["name"]
            # check that "items" is a dict
            if "items" in json_data:
                assert(isinstance(json_data["items"], dict))
            # check that "exits" is a list
            if "exits" in json_data:
                assert(isinstance(json_data["exits"], list))
                # validate all data in each exit
                for exit_data in json_data["exits"]:
                    assert(type(exit_data["destination"]) is str)
                    assert(type(exit_data["name"]) is str)
                    if "other_names" in exit_data:
                        assert(type(exit_data["other_names"]) is list)
                        for other_name in exit_data["other_names"]:
                            assert(type(other_name) is str)
                    if "visibility" in exit_data:
                        filt = json_data["visibility"]
                        assert(filt["type"] == "whitelist" or filt["type"] == "blacklist")
                        assert(type(filt["list"]) is list)
                    if "access" in exit_data:
                        filt = json_data["access"]
                        assert(filt["type"] == "whitelist" or filt["type"] == "blacklist")
                        assert(type(filt["list"]) is list)

             # validate items
            if "items" in json_data:
                pass
        except Exception as ex:
            # modify exception to show what the name is, rethrow
            setattr(ex, "name", name)
            raise ex
        return name, Location(json_data["name"], json_data["description"])

    #TODO: delete all existing exits
    def build_exits(self, *names, chars={}):
        '''This method is always executed on locations
        that have already passed through _do_import. 
        Thus, we can assume the types of each field are correct.
        '''
        for loc_name in names:
            location = self.objects[loc_name]
            json_data = self.file_data[self.object_source[loc_name]]
            if "exits" in json_data:
                for exit_data in json_data["exits"]:
                    dest_name = exit_data["destination"]
                    try:
                        dest = self.objects[exit_data["destination"]]
                    except KeyError:
                        if dest_name in self.exit_failures:
                            self.exit_failures[dest_name]["affected"].append(loc_name)
                        else:
                            new_failure = {"affected" : [loc_name]}
                            if dest_name in self.failures:
                                new_failure["reason"] = "Destination failed to load."
                            else:
                                new_failure["reason"] = "Destination not found."
                            self.exit_failures[dest_name] = new_failure
                        continue
                    # this only handles CharacterClasses
                    # TODO: handle "proper" characters
                    
                    kwargs = dict(exit_data)
                    kwargs["destination"] = dest
                    location.add_exit(Exit(**kwargs))                        

#    def add_items(self):
#        '''looks at the skeletons, adds items for each
#        on fail, an item is simply not added'''
#        for location_name, skeleton in self.skeletons.items():
#            failures = {}
#            # items might be provided, in which case we just continue
#            if "items" not in skeleton:
#                continue
#            for item_name, quantity in skeleton["items"].items():
#                try:
#                    item = library.items[item_name]
#                    quanity = int(quantity)
#                    self.successes[location_name].add_items(item, quanity)
#                except Exception as ex:
#                    failures[item_name] = traceback.format_exc()
#                    # this is an idempotent operation
#                    # even if we re-assign the dict multiple times, it has the same effect
#                    self.item_failures[location_name] = failures
#
#    def add_entities(self):
#        '''looks at skeletons, adds entity for each
#        on fail, an entity is simply not added'''
#        # entities have not been added yet
#        pass

    def all_to_str(self):
        output = super().all_to_str()
        output += "\nEXIT FAILURES\n"
        for location, exits in self.exit_failures.items():
            for dest, exc in exits.items():
                output += str(location) + " -> " + str(dest) + "\n" + exc
        output += "\nITEM FAILURES\n"
        for location, items in self.exit_failures.items():
            output += str(location) + ":\n"
            for item, exc in exits.items():
                output +=  str(dest) + "\n" + exc
        return output


class CharacterClassImporter(Importer):
    def _do_import(self, json_data, locations={}):
        try:
            name = json_data["name"]
            path = json_data["path"]
            
        
            module = importlib.import_module(path.replace('.py', '').replace('/', '.'))
            character_class = getattr(module, name)
            if "starting_location" in json_data:
                starting_location = locations[json_data["starting_location"]]
                character_class.starting_location = starting_location
            if "frequency" in json_data:
                assert isinstance(json_data["frequency"], float)
                character_class.frequency = json_data["frequency"]
            # add other json arguments here
        except Exception as ex:
            setattr(ex, "name", name)
            raise ex
        return str(character_class), character_class

class ItemImporter(Importer):
    def _do_import(self, json_data):
        try:
            name = json_data["name"]
            path = json_data["path"] 
            module = importlib.import_module(path.replace('.py', '').replace('/', '.'))
            item = getattr(module, name)
        except Exception as ex:
            setattr(ex, "name", name)
            raise ex
        return str(item), item

class EntityImporter(Importer):
    pass