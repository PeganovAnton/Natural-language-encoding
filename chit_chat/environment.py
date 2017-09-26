import os
import pickle
import numpy as np
import tensorflow as tf
import inspect
from tensorflow.python import debug as tf_debug


def compute_perplexity(probabilities):
    probabilities[probabilities < 1e-10] = 1e-10
    log_probs = np.log2(probabilities)
    entropy_by_character = np.sum(- probabilities * log_probs, axis=1)
    return np.mean(np.exp2(entropy_by_character))


def compute_loss(predictions, labels):
    predictions[predictions < 1e-10] = 1e-10
    log_predictions = np.log(predictions)
    bpc_by_character = np.sum(- labels * log_predictions, axis=1)
    return np.mean(bpc_by_character)


def compute_bpc(predictions, labels):
    return compute_loss(predictions, labels) / np.log(2)


def compute_accuracy(predictions, labels):
    num_characters = predictions.shape[0]
    num_correct = 0
    for i in range(num_characters):
        if labels[i, np.argmax(predictions, axis=1)[i]] == 1:
            num_correct += 1
    return float(num_correct) / num_characters


def split_to_path_name(path):
    parts = path.split('/')
    name = parts[-1]
    path = '/'.join(parts[:-1])
    return path, name


def create_path(path):
    folder_list = path.split('/')[:-1]
    if len(folder_list) > 0:
        current_folder = folder_list[0]
        for idx, folder in enumerate(folder_list):
            if idx > 0:
                current_folder += ('/' + folder)
            if not os.path.exists(current_folder):
                os.mkdir(current_folder)


def loop_through_indices(filename, start_index):
    path, name = split_to_path_name(filename)
    if '.' in name:
        inter_list = name.split('.')
        extension = inter_list[-1]
        base = '.'.join(inter_list[:-1])
        base += '#%s'
        name = '.'.join([base, extension])

    else:
        name += '#%s'
    if path != '':
        base_path = '/'.join([path, name])
    else:
        base_path = name
    index = start_index
    while os.path.exists(base_path % index):
        index += 1
    return base_path % index


def add_index_to_filename_if_needed(filename, index=None):
    if index is not None:
        return loop_through_indices(filename, index)
    if os.path.exists(filename):
        return loop_through_indices(filename, 1)
    return filename


def match_two_dicts(small_dict, big_dict):
    """Compares keys of small_dict to keys of big_dict and if in small_dict there is a key missing in big_dict throws
    an error"""
    big_dict_keys = big_dict.keys()
    for key in small_dict.keys():
        if key not in big_dict_keys:
            raise KeyError("Wrong argument name '%s'" % key)
    return True


def construct(obj):
    """Used for preventing of not expected changing of class attributes"""
    if isinstance(obj, dict):
        new_obj = dict()
        for key, value in obj.items():
            new_obj[key] = construct(value)
    elif isinstance(obj, list):
        new_obj = list()
        for value in obj:
            new_obj.append(construct(value))
    elif isinstance(obj, tuple):
        base = list()
        for value in obj:
            base.append(construct(value))
        new_obj = tuple(base)
    elif isinstance(obj, str):
        new_obj = str(obj)
    elif isinstance(obj, (int, float, complex, type(None))) or inspect.isclass(obj):
        new_obj = obj
    else:
        raise TypeError("Object of unsupported type was passed to construct function: %s" % type(obj))
    return new_obj


def split_dictionary(dict_to_split, bases):
    """Function takes dictionary dict_to_split and splits it into several dictionaries according to keys of dicts
    from bases"""
    dicts = list()
    for base in bases:
        if isinstance(base, dict):
            base_keys = base.keys()
        else:
            base_keys = base
        new_dict = dict()
        for key, value in dict_to_split.items():
            if key in base_keys:
                new_dict[key] = value
        dicts.append(new_dict)
    return dicts


def link_into_dictionary(old_dictionary, old_keys, new_key):
    """Used in _parse_train_method_arguments to united several kwargs into one dictionary
    Args:
        old_dictionary: a dictionary which entries are to be united
        old_keys: list of keys to be united
        new_key: the key of new entry  containing linked dictionary"""
    linked = dict()
    for old_key in old_keys:
        if old_key in linked:
            linked[old_key] = old_dictionary[old_key]
            del old_dictionary[old_key]
    old_dictionary[new_key] = linked
    return old_dictionary


def paste_into_nested_dictionary(dictionary, searched_key, value_to_paste):
    for key, value, in dictionary.items():
        if key == searched_key:
            dictionary[key] = construct(value_to_paste)
        else:
            if isinstance(value, dict):
                paste_into_nested_dictionary(value, searched_key, value_to_paste)


def search_in_nested_dictionary(dictionary, searched_key):
    for key, value in dictionary.items():
        if key == searched_key:
            return value
        else:
            if isinstance(value, dict):
                returned_value = search_in_nested_dictionary(value, searched_key)
                if returned_value is not None:
                    return returned_value
    return None


class Controller(object):
    """Controller is a class which instances are used for computing changing learning parameters. For example
    learning rate. It is also responsible for training stopping
    Usage:
        1. Construct controller by passing him 'storage' (a dictionary with monitored parameters, usually if used in
        _train method of Environment class 'storage' is self._storage) and specifications. Specifications is
        a dictionary with necessary parameters for computing the controlled value
        2. Use 'get' method to get current value
        3. If you wish to use Controller instance with new specifications you should:
            - add new private method to Controller which will be responsible for processing new specifications. It
              should take no arguments and return monitored value.
            - add elif entry in __init__ method for assigning 'get' with newly created method
            - if new approach requires parameters not provided in self._storage than add them. Also don't forget
              to pass this parameters to _update_storage method in the bottom of _train"""
    @staticmethod
    def create_change_tracking_specifications(specifications):
        if isinstance(specifications, list):
            old_specs = construct(specifications)
        if isinstance(specifications, dict):
            old_specs = [dict(specifications)]
        new_specs = dict()
        new_specs['old_specs'] = old_specs
        new_specs['type'] = 'changes_detector'
        return new_specs

    def __init__(self, storage, specifications):
        self._storage = storage
        self._specifications = specifications
        if self._specifications['type'] == 'limit_steps':
            self.get = self._limit_steps
        elif self._specifications['type'] == 'exponential_decay':
            self.get = self._exponential_decay
        elif self._specifications['type'] == 'fixed':
            self.get = self._fixed
        elif self._specifications['type'] == 'periodic_truth':
            self.get = self._periodic_truth
        elif self._specifications['type'] == 'true_on_steps':
            self.get = self._true_on_steps
        elif self._specifications['type'] == 'changes_detector':
            self._value_controllers = list()
            self._last_values = list()
            for value_specs in self._specifications['old_specs']:
                self._value_controllers.append(Controller(self._storage, value_specs))
                self._last_values.append(self._value_controllers[-1].get())
            self.get = self._changes_detector

    def _changes_detector(self):
        something_changed = False
        for idx, (last_value, controller) in enumerate(zip(self._last_values, self._value_controllers)):
            if last_value != controller.get():
                something_changed = something_changed or True
                self._last_values[idx] = controller.get()
        return something_changed

    def _exponential_decay(self):
        num_stairs = self._storage['step'] // self._specifications['period']
        returned_value = self._specifications['init']
        return returned_value * self._specifications['decay']**num_stairs

    def _limit_steps(self):
        if self._storage['step'] > self._specifications['limit']:
            return False
        else:
            return True

    def _fixed(self):
        return self._specifications['value']

    def _periodic_truth(self):
        if self._storage['step'] % self._specifications['period'] == 0:
            return True
        else:
            return False

    def _true_on_steps(self):
        if self._storage['step'] in self._specifications['steps']:
            return True
        else:
            return False

    @property
    def name(self):
        return self._specifications['name']


class Handler(object):

    def __init__(self,
                 environment_instance,
                 hooks,
                 processing_type,
                 save_path,
                 result_types,
                 summary=False,
                 bpc=False,
                 add_graph_to_summary=False):
        continuous_chit_chat = ['simple_fontain']
        self._processing_type = processing_type
        self._environment_instance = environment_instance
        self._save_path = save_path
        self._result_types = self._environment_instance.put_result_types_in_correct_order(result_types)
        self._bpc = bpc
        self._hooks = hooks
        self._last_run_tensor_order = None
        create_path(self._save_path)
        if self._processing_type == 'train':
            self._train_files = dict()
            self._train_files['loss'] = open(self._save_path +
                                             '/' +
                                             'loss_train.txt',
                                             'a')
            self._train_files['perplexity'] = open(self._save_path +
                                                   '/' +
                                                   'perplexity_train.txt',
                                                   'a')
            self._train_files['accuracy'] = open(self._save_path +
                                                 '/' +
                                                 'accuracy_train.txt',
                                                 'a')
            if self._bpc:
                self._train_files['bpc'] = open(self._save_path +
                                                '/' +
                                                'bpc_train.txt',
                                                'a')
            self._train_files['pickle_tensors'] = open(self._save_path +
                                                       '/' +
                                                       'tensors_train.pickle',
                                                       'ab')
            self._train_dataset_name = None
            self._dataset_specific = dict()
            self._controllers = None
            self._results_collect_interval=None
            self._print_per_collected=None
            self._example_per_print=None
            self._train_tensor_schedule=None
            self._validation_tensor_schedule=None
            self._printed_result_types=None
            self._printed_controllers=None
            if summary:
                self._writer = tf.summary.FileWriter(self._save_path + '/' + 'summary')
                if add_graph_to_summary:
                    self._writer.add_graph(tf.get_default_graph())
            self._environment_instance.init_storage(steps=list(),
                                                    loss=list(),
                                                    perplexity=list(),
                                                    accuracy=list(),
                                                    bpc=list())
            self._training_step = None
            self._accumulation_is_performed = False
            self._accumulated_tensors = dict()
            self._accumulated = dict(loss=None, perplexity=None, accuracy=None)
            if self._bpc:
                self._accumulated['bpc'] = None
        if self._processing_type == 'test':
            self.process_results = self._process_validation_results
            self._training_step = None
            self._name_of_dataset_on_which_accumulating = None
            self._accumulated_tensors = dict()
            self._accumulated = dict(loss=None, perplexity=None, accuracy=None)
            if self._bpc:
                self._accumulated['bpc'] = None

        # The order in which tensors are presented in the list returned by get_additional_tensors method
        # It is a list. Each element is either tensor alias or a tuple if corresponding hook is pointing to a list of
        # tensors. Such tuple contains tensor alias, and sizes of nested lists


    def _switch_datasets(self, train_dataset_name, validation_dataset_names):
        self._train_dataset_name = train_dataset_name
        for dataset_name in validation_dataset_names:
            if dataset_name not in self._dataset_specific.keys():
                new_files = dict()
                new_files['loss'] = open(self._save_path +
                                         '/' +
                                         'loss_validation_%s.txt' % dataset_name,
                                         'a')
                new_files['perplexity'] = open(self._save_path +
                                               '/' +
                                               'perplexity_validation_%s.txt' % dataset_name,
                                               'a')
                new_files['accuracy'] = open(self._save_path +
                                             '/' +
                                             'accuracy_validation_%s.txt' % dataset_name,
                                             'a')
                if self._bpc:
                    new_files['bpc'] = open(self._save_path +
                                            '/' +
                                            'bpc_validation_%s.txt' % dataset_name,
                                            'a')
                new_files['pickle_tensors'] = open(self._save_path +
                                                   '/' +
                                                   'tensors_validation_%s.pickle' % dataset_name,
                                                   'ab')
                new_storage_keys = dict()
                new_storage_keys['steps'] = 'valid_%s_steps' % dataset_name
                new_storage_keys['loss'] = 'valid_%s_loss' % dataset_name
                new_storage_keys['perplexity'] = 'valid_%s_perplexity' % dataset_name
                new_storage_keys['accuracy'] = 'valid_%s_accuracy' % dataset_name
                if self._bpc:
                    new_storage_keys['bpc'] = 'valid_%s_bpc' % dataset_name
                self._dataset_specific[dataset_name] = {'name': dataset_name,
                                                        'files': new_files,
                                                        'storage_keys': new_storage_keys}
                init_dict = dict()
                for storage_key in new_storage_keys.values():
                    if not self._environment_instance.check_if_key_in_storage(storage_key):
                        init_dict[storage_key] = list()
                self._environment_instance.init_storage(**init_dict)
        for key in self._dataset_specific.keys():
            if key not in validation_dataset_names:
                for file_d in self._dataset_specific[key]['files'].values():
                    file_d.close()
                del self._dataset_specific[key]

    def set_new_run_schedule(self, schedule, train_dataset_name, validation_dataset_names):
        self._results_collect_interval = schedule['to_be_collected_while_training']['results_collect_interval']
        self._print_per_collected = schedule['to_be_collected_while_training']['print_per_collected']
        self._example_per_print = schedule['to_be_collected_while_training']['example_per_print']
        self._train_tensor_schedule = schedule['train_tensor_schedule']
        self._validation_tensor_schedule = schedule['validation_tensor_schedule']
        self._printed_controllers = schedule['printed_controllers']
        self._printed_result_types = schedule['printed_result_types']
        self._switch_datasets(train_dataset_name, validation_dataset_names)

    def set_controllers(self, controllers):
        self._controllers = controllers

    def start_accumulation(self, dataset_name, training_step=None):
        self._name_of_dataset_on_which_accumulating = dataset_name
        self._training_step = training_step
        for res_type in self._accumulated.keys():
            self._accumulated[res_type] = list()

    def stop_accumulation(self):
        means = dict()
        for key, value_list in self._accumulated.items():
            mean = sum(value_list) / len(value_list)
            file_d = self._dataset_specific[self._name_of_dataset_on_which_accumulating]['files'][key]
            if self._training_step is not None:
                file_d.write('%s %s\n' % (self._training_step, mean))
            else:
                file_d.write('%s\n' % (sum(value_list) / len(value_list)))
            means[key] = mean
        storage_keys = self._dataset_specific[self._name_of_dataset_on_which_accumulating]['storage_keys']
        self._environment_instance.append_to_storage(
            **dict([(storage_key, means[key]) for key, storage_key in storage_keys.items() if key != 'steps']))
        self._print_all(regime='validation',
                        message='results on validation dataset %s' % self._name_of_dataset_on_which_accumulating,
                        **means)
        self._training_step = None
        self._name_of_dataset_on_which_accumulating = None
        self._save_accumulated_tensors()

    # def _effectiveness_specs(self,
    #                          loss=None,
    #                          prediction=None,
    #                          labels=None):
    #     if prediction is not None:
    #         perplexity = compute_perplexity(prediction)
    #     else:
    #         perplexity = None
    #     if loss is None:
    #         if prediction is not None and labels is not None:
    #             loss = compute_loss(prediction, labels)
    #     if prediction is not None and labels is not None:
    #         accuracy = compute_accuracy(prediction, labels)
    #     else:
    #         accuracy = None
    #     if self._bpc and loss is not None:
    #         bpc = loss / np.log(2)
    #     else:
    #         bpc = None
    #     return [loss, perplexity, accuracy, bpc]

    def _process_validation_results(self,
                                    step,
                                    validation_res):
        if self._bpc:
            [loss, perplexity, accuracy, bpc] = validation_res[1:5]
        else:
            [loss, perplexity, accuracy] = validation_res[1:4]
        if self._bpc:
            self._accumulate_several_data(['loss', 'perplexity', 'accuracy', 'bpc'], [loss, perplexity, accuracy, bpc])
            self._accumulate_tensors(step, validation_res[5:])
        else:
            self._accumulate_several_data(['loss', 'perplexity', 'accuracy'], [loss, perplexity, accuracy])
            self._accumulate_tensors(step, validation_res[4:])

    def _cope_with_tensor_alias(self,
                                alias):
        if not isinstance(self._hooks[alias], list):
            return [self._hooks[alias]], 1
        add_tensors = list()
        order = [alias, len(self._hooks[alias])]
        counter = 0
        if isinstance(self._hooks[alias][0], list):
            order.append(len(self._hooks[alias][0]))
            for elem in self._hooks[alias]:
                for tensor in elem:
                    add_tensors.append(tensor)
                    counter += 1
        else:
            for tensor in self._hooks[alias]:
                add_tensors.append(tensor)
                counter += 1
        return add_tensors, counter

    def _save_datum(self, descriptor, step, datum, processing_type, dataset_name):
        if processing_type == 'train':
            self._train_files[descriptor].write('%s %s\n' % (step, datum))
        elif processing_type == 'validation':
            self._dataset_specific[dataset_name]['files'][descriptor].write('%s %s\n' % (step, datum))

    def _save_several_data(self,
                           descriptors,
                           step,
                           data,
                           processing_type='train',
                           dataset_name=None):
        for descriptor, datum in zip(descriptors, data):
            if datum is not None:
                self._save_datum(descriptor, step, datum, processing_type, dataset_name)

    def _save_accumulated_tensors(self):
        pass

    def _accumulate_several_data(self, descriptors, data):
        for descriptor, datum in zip(descriptors, data):
            if datum is not None:
                self._accumulated[descriptor].append(datum)

    def get_tensors(self, regime, step, with_assistant=False):
        tensors = list()
        self._last_run_tensor_order = dict()
        pointer = 0
        current = dict()
        self._last_run_tensor_order['basic'] = current
        start = pointer
        if regime == 'train':
            if with_assistant:
                tensors.append(self._hooks['train_op_with_assistant'])
                current['train_op_with_assistant'] = [pointer, pointer+1]
                pointer += 1
            else:
                tensors.append(self._hooks['train_op'])
                current['train_op'] = [pointer, pointer + 1]
                pointer += 1
            for res_type in self._result_types:
                tensors.append(self._hooks[res_type])
                current[res_type] = [pointer, pointer + 1]
                pointer += 1
            self._last_run_tensor_order['basic']['borders'] = [start, pointer]

            if self._train_tensor_schedule is not None:
                additional_tensors = self._get_additional_tensors(self._train_tensor_schedule, step, pointer)
            tensors.extend(additional_tensors)
        if regime == 'validation':
            tensors.append(self._hooks['validation_predictions'])
            for res_type in self._result_types:
                tensors.append(self._hooks['validation_' + res_type])
                current['validation_' + res_type] = [pointer, pointer + 1]
                pointer += 1
            self._last_run_tensor_order['basic']['borders'] = [start, pointer]

            if self._validation_tensor_schedule is not None:
                additional_tensors = self._get_additional_tensors(self._validation_tensor_schedule, step, pointer)
            tensors.extend(additional_tensors)
        return tensors

    def _get_additional_tensors(self,
                                schedule,
                                step,
                                start_pointer):
        additional_tensors = list()
        self._last_run_tensor_order = dict()
        pointer = start_pointer
        for tensors_use, tensors_schedule in schedule.items():
            self._last_run_tensor_order[tensors_use] = dict()
            start = pointer
            if isinstance(tensors_schedule, dict):
                for tensor_alias, tensor_schedule in tensors_schedule.items():
                    if isinstance(tensor_schedule, list):
                        if step in tensor_schedule:
                            add_tensors, counter = self._cope_with_tensor_alias(tensor_alias)
                            additional_tensors.extend(add_tensors)
                            self._last_run_tensor_order[tensors_use][tensor_alias] = [pointer, pointer + counter]
                            pointer += counter
                    elif isinstance(tensor_schedule, int):
                        if step % tensor_schedule == 0:
                            add_tensors, counter = self._cope_with_tensor_alias(tensor_alias)
                            additional_tensors.extend(add_tensors)
                            self._last_run_tensor_order[tensors_use][tensor_alias] = [pointer, pointer + counter]
                            pointer += counter
            elif isinstance(tensors_schedule, list):
                for tensor_alias in tensors_schedule:
                    add_tensors, counter = self._cope_with_tensor_alias(tensor_alias)
                    additional_tensors.extend(add_tensors)
                    self._last_run_tensor_order[tensors_use][tensor_alias] = [pointer, pointer + counter]
                    pointer += counter
            self._last_run_tensor_order[tensors_use]['borders'] = [start, pointer]
        return additional_tensors

    def _print_tensors(self, tensors, schedule):
        pass

    def _accumulate_tensors(self, step, tensors):
        pass

    def _save_tensors(self, tensors):
        pass

    def _print_controllers(self):
        if self._controllers is not None:
            for controller in self._controllers:
                # if isinstance(controller, Controller):
                #     print(controller.name)
                # if isinstance(controller, list):
                #     for c in controller:
                #         if isinstance(c, Controller):
                #             print(c.name)
                #         else:
                #             print(c)
                if controller.name in self._printed_controllers:
                    print('%s:' % controller.name, controller.get())

    def _print_all(self,
                   indents=[0, 0],
                   regime='train',
                   **kwargs):
        for _ in range(indents[0]):
            print('')
        if regime == 'train':
            if 'step' in kwargs:
                print('step:', kwargs['step'])
            self._print_controllers()
        if 'message' in kwargs:
            print(kwargs['message'])
        for key, value in kwargs.items():
            if key != 'tensors' and key != 'step' and key != 'message' and key in self._printed_result_types:
                print('%s:' % key, value)
        if 'tensors' in kwargs:
            self._print_tensors(kwargs['tensors'], self._train_tensor_schedule)
        for _ in range(indents[1]):
            print('')

    def _process_train_results(self,
                               step,
                               train_res):
        [loss, perplexity, accuracy] = train_res[1:4]
        if self._bpc:
            bpc = train_res[4]
            additional_tensors = train_res[5:]
        else:
            additional_tensors = train_res[4:]
        if step % (self._results_collect_interval * self._print_per_collected) == 0:
            if self._bpc:
                self._print_all(indents=[2, 0],
                                step=step,
                                loss=loss,
                                bpc=bpc,
                                perplexity=perplexity,
                                accuracy=accuracy,
                                tensors=additional_tensors,
                                message='results on train dataset')
            else:
                self._print_all(indents=[2, 0],
                                step=step,
                                loss=loss,
                                perplexity=perplexity,
                                accuracy=accuracy,
                                tensors=additional_tensors,
                                message='results on train dataset')
        if step % self._results_collect_interval == 0:
            self._save_several_data(['loss', 'perplexity', 'accuracy', 'bpc'], step, [loss, perplexity, accuracy, bpc])
            self._environment_instance.append_to_storage(loss=loss,
                                                         bpc=bpc,
                                                         perplexity=perplexity,
                                                         accuracy=accuracy)
        self._save_tensors(train_res[3:])

    def process_results(self, step, res, regime):
        if regime == 'train':
            self._process_train_results(step, res)
        if regime == 'validation':
            self._process_validation_results(step, res)

    def close(self):
        for file in self._train_files.values():
            file.close()
        for dataset in self._dataset_specific.values():
            for file_d in dataset['files'].values():
                file_d.close()

class InvalidArgumentError(Exception):
    def __init__(self, msg, value, name, allowed_values):
        super(InvalidArgumentError, self).__init__(msg)
        self._msg = msg
        self._value = value
        self._name = name
        self._allowed_values = allowed_values


def perplexity_tensor(**kwargs):
    probabilities = kwargs['probabilities']
    ln2 = np.log(2)
    shape = probabilities.get_shape().as_list()
    probabilities = tf.where(probabilities > 1e-10, probabilities, np.full(tuple(shape), 1e-10))
    log_probabilities = tf.log(probabilities) / ln2
    entropy = tf.reduce_sum(- probabilities * log_probabilities, axis=1)
    perplexity = tf.exp(ln2 * entropy)
    return tf.reduce_mean(perplexity, name="mean_perplexity")


def loss_tensor(**kwargs):
    predictions = kwargs['predictions']
    labels = kwargs['labels']
    shape = predictions.get_shape().as_list()
    predictions = tf.where(predictions > 1e-10, predictions, np.full(tuple(shape), 1e-10))
    log_predictions = tf.log(predictions)
    loss_on_characters = tf.reduce_sum(-labels * log_predictions, axis=1)
    return tf.reduce_mean(loss_on_characters)


def bpc_tensor(**kwargs):
    return kwargs['loss'] / np.log(2)


def accuracy_tensor(**kwargs):
    predictions = kwargs['predictions']
    labels = kwargs['labels']
    predictions = tf.argmax(predictions, axis=1)
    labels = tf.argmax(labels, axis=1)
    return tf.reduce_mean(tf.to_float(tf.equal(predictions, labels)))


class Environment(object):

    @staticmethod
    def put_result_types_in_correct_order(result_types):
        correct_order = ['loss', 'perplexity', 'accuracy', 'bpc']
        sorted_types = list()
        for result_type in correct_order:
            if result_type in result_types:
                sorted_types.append(result_type)
        return sorted_types

    def __init__(self,
                 pupil_class,
                 batch_generator_classes,
                 vocabulary=None,
                 datasets=None,
                 filenames=None,
                 texts=None,
                 assistant_class=None):
        """ Initializes environment class
        Args:
            pupil_class: is a class to which pupil model belongs
            assistant_class: is a class to which assistant model belongs if it is provided
            data_filenames: contains paths to a files with data for model training, validation and testing
                has to be a dictionary in which keys are names of datasets, values are strings with paths to files
            batch_generator_classes: """

        self._pupil_class = pupil_class
        self._pupil_type = self._pupil_class.get_name()
        self._assistant_class = assistant_class

        if datasets is not None:
            self._datasets = dict()
            for dataset in datasets:
                self._datasets[dataset[1]] = dataset
        else:
            self._datasets = dict()

        self._vocabulary = vocabulary

        if filenames is not None:
            for filename in filenames:
                key, value = self._process_dataset_filename(filename)
                self._datasets[key] = [value, key]

        if texts is not None:
            for text in texts:
                key, value = self._process_input_text_dataset(text)
                self._datasets[key] = [value, key]

        if not isinstance(batch_generator_classes, dict):
            self._batch_generator_classes = {'default': batch_generator_classes}
        else:
            self._batch_generator_classes = batch_generator_classes

        # # Just initializing attributes containing arguments for model building
        # self._pupil_building_parameters = self._pupil_class.get_building_parameters()
        # if self._assistant_class is not None:
        #     self._assistant_building_parameters = self._assistant_class.get_building_parameters()

        # An attributes containing instance of self._model_class. While graph is not built self._model is None
        self._pupil = None
        self._assistant = None

        # An attribute holding tensors which could be run. It has the form of dictionary which keys are user specified
        # descriptors of tensors and are tensors themselves
        self._pupil_hooks = dict()
        self._assistant_hooks = dict()

        # List containing fuses. They are used for testing the model. You may feed them to the model and see how it
        # continues generating after that
        self._fuses = list()

        # An attribute holding session. Default value when there is no active sessions is None
        self._session = None

        train_perplexity_function = dict(f=perplexity_tensor,
                                         hooks={'probabilities': 'predictions'},
                                         tensor_names=dict(),
                                         output_hook_name='perplexity')
        valid_perplexity_function = dict(f=perplexity_tensor,
                                         hooks={'probabilities': 'validation_predictions'},
                                         tensor_names=dict(),
                                         output_hook_name='validation_perplexity')
        valid_loss_function = dict(f=loss_tensor,
                                   hooks={'predictions': 'validation_predictions',
                                          'labels': 'validation_labels'},
                                   tensor_names=dict(),
                                   output_hook_name='validation_loss')
        train_bpc_function = dict(f=bpc_tensor,
                                  hooks={'loss': 'loss'},
                                  tensor_names=dict(),
                                  output_hook_name='bpc')
        valid_bpc_function=dict(f=bpc_tensor,
                                hooks={'loss': 'validation_loss'},
                                tensor_names=dict(),
                                output_hook_name='validation_bpc')
        train_accuracy_function=dict(f=accuracy_tensor,
                                     hooks={'predictions': 'predictions',
                                            'labels': 'labels'},
                                     tensor_names=dict(),
                                     output_hook_name='accuracy')
        valid_accuracy_function=dict(f=accuracy_tensor,
                                     hooks={'predictions': 'validation_predictions',
                                            'labels': 'validation_labels'},
                                     tensor_names=dict(),
                                     output_hook_name='validation_accuracy')

        self._tensor_build_functions = {'perplexity': train_perplexity_function,
                                        'validation_perplexity': valid_perplexity_function,
                                        'validation_loss': valid_loss_function,
                                        'bpc': train_bpc_function,
                                        'validation_bpc': valid_bpc_function,
                                        'accuracy': train_accuracy_function,
                                        'validation_accuracy': valid_accuracy_function}

        tensor_schedule = {'train_print_tensors': dict(),
                           'train_save_tensors': dict(),
                           'train_print_text_tensors': dict(),
                           'train_save_text_tensors': dict(),
                           'train_summary_tensors': dict()}

        valid_tensor_schedule = {'valid_print_tensors': dict(),
                                 'valid_save_text_tensors': dict()}

        fuse_tensors = {'fuse_print_tensors': dict(), 'fuse_save_tensors': dict()}

        # Every results_collect_interval-th step BPC, accuracy, perplexity are collected
        # Every print_per_collected-th point containing BPC, accuracy and perplexity is printed
        # Together with every example_per_print-th point example is printed
        default_collected_while_training = {'results_collect_interval': 100,
                                            'print_per_collected': 1,
                                            'example_per_print': 1}

        default_collected_on_validation = {}

        default_learning_rate_control = {'init': 0.002,
                                         'decay': 0.8,
                                         'period': 1000,
                                         'type': 'exponential_decay',
                                         'name': 'learning_rate'}

        if len(self._datasets) > 0:
            default_dataset = self._datasets[0]
        else:
            default_dataset = None
        _, gens = zip(*sorted(self._batch_generator_classes.items()))
        default_batch_generator = gens[0]
        self._default_train_method_args = dict(
            start_specs={'allow_soft_placement': False,
                         'gpu_memory': None,
                         'log_device_placement': False,
                         'restore_path': None,
                         'save_path': None,
                         'result_types': self.put_result_types_in_correct_order(
                             ['loss', 'perplexity', 'accuracy', 'bpc']),
                         'summary': False,
                         'add_graph_to_summary': False,
                         'batch_generator_class': default_batch_generator},
            run=dict(
                train_specs={'assistant': None,
                             'learning_rate': construct(default_learning_rate_control),
                             'additions_to_feed_dict': None,
                             'stop': {'type': 'limit_steps', 'limit': 10000, 'name': 'stop'},
                             'train_dataset': default_dataset,
                             'batch_size': {'type': 'fixed', 'value': 64, 'name': 'batch_size'},
                             'train_batch_kwargs': dict(),
                             'checkpoint_steps': None,
                             'debug': None,
                             'validation_datasets': None,
                             'validation_batch_size': 1,
                             'valid_batch_kwargs': dict()},
                schedule={'to_be_collected_while_training': construct(default_collected_while_training),
                          'printed_result_types':  self.put_result_types_in_correct_order(
                             ['loss']),
                          'printed_controllers': ['learning_rate'],
                          'fuses': None,
                          'fuse_tensors': construct(fuse_tensors),
                          'replicas': None,
                          'random': {'number_of_runs': 5,
                                     'length': 80},
                          'train_tensor_schedule': construct(tensor_schedule),
                          'validation_tensor_schedule': construct(valid_tensor_schedule)}
                    )
                                               )

        # This attribute is used solely for controlling learning parameters (learning rate, additions_to_feed_dict)
        # It is used by instances of Controller class
        # BPI stands for bits per input. It is cross entropy computed using logarithm for base 2
        self._handler = None
        self._storage = {'step': None}
        self._collected_result = None

    def build(self, **kwargs):
        """A method building the graph
        Args:
            kwargs: key word arguments passed to self._model_class constructor
            :type kwargs: dictionary"""

        # checking if passed required arguments
        self._pupil_class.check_kwargs(**kwargs)

        # Building the graph
        self._pupil = self._pupil_class(**kwargs)

        # getting default hooks
        default_hooks = self._pupil.get_default_hooks()
        self._pupil_hooks.update(default_hooks)

    def _split_to_loss_and_not_loss_names(self, names):
        loss_names = list()
        not_loss_names = list()
        for name in names:
            if 'loss' in name:
                loss_names.append(name)
            else:
                not_loss_names.append(name)
        return loss_names, not_loss_names

    def _arguments_for_new_tensor_building(self, hooks, tensor_names):
        arguments = dict()
        for key, value in hooks.items():
            if value not in self._pupil_hooks:
                stars = '\n**********\n'
                msg = "Warning! Adding to hooks shapeless placeholder of type tf.float32 with alias '%s'" % value
                print(stars + msg + stars)
                self._pupil_hooks[value] = tf.placeholder(tf.float32)
            arguments[key] = self._pupil_hooks[value]
        for key, value in tensor_names.items():
            arguments[key] = tf.get_tensor_by_name(value)
        return arguments

    def _add_hook(self, builder_name, model_type='pupil'):
        if builder_name in self._tensor_build_functions:
            build_instructions = self._tensor_build_functions[builder_name]
            kwargs = self._arguments_for_new_tensor_building(build_instructions['hooks'],
                                                             build_instructions['tensor_names'])
            new_tensor = build_instructions['f'](**kwargs)
            if model_type == 'pupil':
                self._pupil_hooks[build_instructions['output_hook_name']] = new_tensor
            else:
                self._assistant_hooks[build_instructions['output_hook_name']] = new_tensor
        else:
            stars = '\n**********\n'
            msg = "Warning! Adding to hooks shapeless placeholder of type tf.float32 with alias '%s'" % builder_name
            print(stars + msg + stars)
            if model_type == 'pupil':
                self._pupil_hooks[builder_name] = tf.placeholder(tf.float32)
            else:
                self._assistant_hooks[builder_name] = tf.placeholder(tf.float32)

    def _add_several_hooks(self, builder_names, model_type='pupil'):
        loss_names, not_loss_names = self._split_to_loss_and_not_loss_names(builder_names)
        for loss_name in loss_names:
            self._add_hook(loss_name, model_type=model_type)
        for not_loss_name in not_loss_names:
            self._add_hook(not_loss_name, model_type=model_type)

    @classmethod
    def _update_dict(cls, dict_to_update, update):
        """Checks if update matches dict_to_update and updates it
        Args:
            dict_to_update: a class attribute of type dict which should be updated
            update: dict which is used for updating"""
        keys_all_right = match_two_dicts(update, dict_to_update)
        if keys_all_right:
            for key, value in update.items():
                if isinstance(value, dict):
                    cls._update_dict(dict_to_update[key], update[key])
                else:
                    dict_to_update[key] = construct(value)

    @property
    def default_train_method_args(self):
        return construct(self._default_train_method_args)

    @default_train_method_args.setter
    def default_train_method_args(self, update):
        """update is a dictionary which should match keys of self._pupil_default_training"""
        self._update_dict(self._default_train_method_args, update)

    def get_default_method_parameters(self,
                                      method_name):
        if method_name == 'train':
            return self.default_train_method_args
        return None

    def _start_session(self, allow_soft_placement, log_device_placement, gpu_memory):
        """Starts new session with specified parameters. If there is opend session closes it"""
        if self._session is not None:
            print('Warning: there is an opened session already. Closing it')
            self._session.close()

        config = tf.ConfigProto(allow_soft_placement=allow_soft_placement,
                                log_device_placement=log_device_placement,
                                gpu_options=tf.GPUOptions(per_process_gpu_memory_fraction=gpu_memory))
        self._session = tf.Session(config=config)

    def _close_session(self):
        self._session.close()
        self._session = None

    def init_storage(self, **kwargs):
        for key, value in kwargs.items():
            self._storage[key] = value

    def append_to_storage(self, **kwargs):
        for key, value in kwargs.items():
            self._storage[key].append(value)

    def set_in_storage(self, **kwargs):
        for key, value in kwargs.items():
            self._storage[key] = value

    def check_if_key_in_storage(self, key):
        return key in self._storage

    def _create_checkpoint(self, step, checkpoints_path, model_type='pupil'):
        path = checkpoints_path + '/' + str(step)
        if model_type == 'pupil':
            self._pupil_hooks['saver'].save(self._session, path)
        elif model_type == 'assistant':
            self._assistant_hooks['saver'].save(self._session, path)

    def test(self, **kwargs):
        pass

    def _on_fuses(self,
                  batch_generator_class,
                  fuses,
                  fuse_tensors,
                  additional_feed_dict=None):
        if 'reset_validation_state' in self._pupil_hooks:
            self._session.run(self._pupil_hooks['reset_validation_state'])
        generator = batch_generator_class(by_character=True)
        for fuse in fuses:
            for repeat_idx in range(fuse['num_repeats']):
                for char_idx, char in enumerate(fuse):
                    vec = generator.char2vec(char)
                    feed_dict = {self._pupil_hooks['validation_inputs']: vec}
                    feed_dict = dict(feed_dict.items(), additional_feed_dict.items())
                    fuse_operations = [self._pupil_hooks['validation_prediction']]
                    fuse_operations.extend([self._pupil_hooks[key] for key in fuse_tensors])
                    fuse_res = self._session.run(fuse_operations, feed_dict=feed_dict)
                    self._process_results(fuse_res)
                vec = generator.pred2vec(fuse_res[0])
                feed_dict = {self._pupil_hooks['validation_inputs']: vec}
                feed_dict = dict(feed_dict.items(), additional_feed_dict.items())
                fuse_operations = [self._pupil_hooks['validation_prediction']]
                fuse_operations.extend([self._pupil_hooks[key] for key in fuse_tensors])
                fuse_res = self._session.run(fuse_operations, feed_dict=feed_dict)
                self._process_results(fuse_res)

    def _validate(self,
                  batch_generator_class,
                  validation_dataset,
                  validation_batch_size,
                  valid_batch_kwargs,
                  training_step=None,
                  additional_feed_dict=None):

        if 'reset_validation_state' in self._pupil_hooks:
            self._session.run(self._pupil_hooks['reset_validation_state'])
        valid_batches = batch_generator_class(validation_dataset[0], validation_batch_size, **valid_batch_kwargs)
        length = valid_batches.get_dataset_length()
        inputs, labels = valid_batches.next()
        step = 0
        self._handler.start_accumulation(validation_dataset[1], training_step=training_step)
        while step < length:

            validation_operations = self._handler.get_tensors('validation', step)
            feed_dict = {self._pupil_hooks['validation_inputs']: inputs,
                         self._pupil_hooks['validation_labels']: labels}
            if additional_feed_dict is not None:
                feed_dict = dict(feed_dict.items(), additional_feed_dict.items())
            valid_res = self._session.run(validation_operations, feed_dict=feed_dict)
            self._handler.process_results(training_step, valid_res, 'validation')
            step += 1
            inputs, labels = valid_batches.next()
        self._handler.stop_accumulation()

    def _from_random_fuse(self):
        pass

    def _from_fuses(self):
        pass

    def _on_replicas(self):
        pass

    def _get_all_tensors_from_schedule(self, schedule):
        returned_list = list()
        for _, dict_with_tensors in schedule.items():
            for tensor_alias in dict_with_tensors.keys():
                returned_list.append(tensor_alias)
        return returned_list

    def _all_tensor_aliases_from_train_arguments(self, start_specs, run_specs_set):
        list_of_required_tensors_aliases = list()
        list_of_required_tensors_aliases.extend(start_specs['result_types'])
        for result_type in start_specs['result_types']:
            list_of_required_tensors_aliases.append('validation_' + result_type)
        for run_specs in run_specs_set:
            train_aliases = self._get_all_tensors_from_schedule(run_specs['schedule']['train_tensor_schedule'])
            list_of_required_tensors_aliases.extend(train_aliases)
            valid_aliases = self._get_all_tensors_from_schedule(run_specs['schedule']['validation_tensor_schedule'])
            list_of_required_tensors_aliases.extend(valid_aliases)
        return list_of_required_tensors_aliases

    def _create_all_missing_hooks(self, list_of_tensor_aliases, model_type='pupil'):
        missing = list()
        for tensor_alias in list_of_tensor_aliases:
            if model_type == 'pupil':
                if tensor_alias not in self._pupil_hooks:
                    missing.append(tensor_alias)
            if model_type == 'assistant':
                if tensor_alias not in self._assistant_hooks:
                    missing.append(tensor_alias)
        self._add_several_hooks(missing, model_type=model_type)

    def _build_batch_kwargs(self, unprepaired_kwargs):
        kwargs = dict()
        for key, arg in unprepaired_kwargs.items():
            if isinstance(arg, Controller):
                kwargs[key] = arg.get()
            else:
                kwargs[key] = arg
        return kwargs

    def _train(self,
               run_specs,
               checkpoints_path,
               batch_generator_class,
               init_step=0):
        """It is a method that does actual training and responsible for one training pass through dataset. It is called
        from train method (maybe several times)
        Args:
            kwargs should include all entries defined in self._pupil_default_training"""
        #print("_train method 'run_specs':\n", run_specs)
        train_specs = construct(run_specs['train_specs'])
        schedule = construct(run_specs['schedule'])
        step = init_step

        # creating batch generator

        # resetting step in control_storage
        self.init_storage(step=step)
        learning_rate_controller = Controller(self._storage,
                                              train_specs['learning_rate'])
        train_feed_dict_additions = train_specs['additions_to_feed_dict']
        if train_feed_dict_additions is not None:
            additional_controllers = list()
            for addition in train_feed_dict_additions:
                additional_controllers.append(Controller(self._storage, addition))
        else:
            additional_controllers = None

        if train_specs['stop']['type'] == 'limit_steps':
            train_specs['stop']['limit'] += init_step
        should_continue = Controller(self._storage, train_specs['stop'])

        to_be_collected_while_training = schedule['to_be_collected_while_training']
        collect_interval = to_be_collected_while_training['results_collect_interval']
        print_per_collected = to_be_collected_while_training['print_per_collected']

        valid_period = collect_interval * print_per_collected
        it_is_time_for_validation = Controller(self._storage,
                                               {'type': 'periodic_truth',
                                                'period': valid_period})

        if train_specs['checkpoint_steps'] is not None:
            if train_specs['checkpoint_steps']['type'] == 'true_on_steps':
                for idx in range(len(train_specs['checkpoint_steps']['steps'])):
                    train_specs['checkpoint_steps']['steps'][idx] += init_step
            it_is_time_to_create_checkpoint = Controller(self._storage, train_specs['checkpoint_steps'])
        else:
            it_is_time_to_create_checkpoint = Controller(self._storage,
                                                         {'type': 'true_on_steps',
                                                          'steps': []})

        batch_size_controller = Controller(self._storage, train_specs['batch_size'])
        batch_size_change_tracker_specs = Controller.create_change_tracking_specifications(train_specs['batch_size'])
        batch_size_should_change = Controller(self._storage, batch_size_change_tracker_specs)

        if train_specs['debug'] is not None:
            should_start_debugging = Controller(self._storage, train_specs['debug'])
        else:
            should_start_debugging = Controller(self._storage,
                                                {'type': 'true_on_steps',
                                                 'steps': []})

        train_batch_kwargs = dict()
        train_batch_kwargs_controller_specs = list()
        for key, batch_arg in train_specs['train_batch_kwargs'].items():
            if isinstance(batch_arg, dict):
                if 'type' in batch_arg:
                    train_batch_kwargs[key] = Controller(self._storage, batch_arg)
                    train_batch_kwargs_controller_specs.append(batch_arg)
                else:
                    train_batch_kwargs[key] = batch_arg
            else:
                train_batch_kwargs[key] = batch_arg
        change_tracker_specs = Controller.create_change_tracking_specifications(
            train_batch_kwargs_controller_specs)
        batch_generator_specs_should_change = Controller(self._storage, change_tracker_specs)

        controllers_for_printing = [learning_rate_controller]
        if additional_controllers is not None:
            controllers_for_printing.extend(additional_controllers)
        controllers_for_printing.append(batch_size_controller)
        batch_kwargs_controllers = list()
        for batch_kwarg in train_batch_kwargs.values():
            if isinstance(batch_kwarg, Controller):
                batch_kwargs_controllers.append(batch_kwarg)
        controllers_for_printing.extend(batch_kwargs_controllers)
        self._handler.set_new_run_schedule(schedule,
                                           train_specs['train_dataset'][1],
                                           [dataset[1] for dataset in train_specs['validation_datasets']])
        print(controllers_for_printing)
        self._handler.set_controllers(controllers_for_printing)

        batch_size = batch_size_controller.get()
        tb_kwargs = self._build_batch_kwargs(train_batch_kwargs)
        train_batches = batch_generator_class(train_specs['train_dataset'][0], batch_size, **tb_kwargs)
        feed_dict = dict()
        while should_continue.get():
            if should_start_debugging.get():
                self._session = tf_debug.LocalCLIDebugWrapperSession(self._session)
                self._session.add_tensor_filter("has_inf_or_nan", tf_debug.has_inf_or_nan)

            if batch_size_should_change.get():
                batch_size = batch_size_controller.get()
                train_batches.change_batch_size(batch_size)

            if batch_generator_specs_should_change.get():
                tb_kwargs = self._build_batch_kwargs(train_batch_kwargs)
                train_batches.change_specs(**tb_kwargs)

            if it_is_time_to_create_checkpoint.get():
                self._create_checkpoint(step, checkpoints_path)

            learning_rate = learning_rate_controller.get()
            train_inputs, train_labels = train_batches.next()
            feed_dict[self._pupil_hooks['learning_rate']] = learning_rate
            if isinstance(self._pupil_hooks['inputs'], list):
                for input_tensor, input_value in zip(self._pupil_hooks['inputs'], train_inputs):
                    feed_dict[input_tensor] = input_value
            else:
                feed_dict[self._pupil_hooks['inputs']] = train_inputs
            if isinstance(self._pupil_hooks['labels'], list):
                for label_tensor, label_value in zip(self._pupil_hooks['labels'], train_labels):
                    feed_dict[label_tensor] = label_value
            else:
                feed_dict[self._pupil_hooks['labels']] = train_labels
            if train_feed_dict_additions is not None:
                for addition, add_controller in zip(train_feed_dict_additions, additional_controllers):
                    feed_dict[self._pupil_hooks[addition['name']]] = add_controller.get()
            train_operations = self._handler.get_tensors('train', step)
            train_res = self._session.run(train_operations, feed_dict=feed_dict)
            # here loss is given in bits per input (BPI)

            self._handler.process_results(step, train_res, 'train')
            if it_is_time_for_validation.get():
                for validation_dataset in train_specs['validation_datasets']:
                    if train_feed_dict_additions is None:
                        valid_add_feed_dict = None
                    else:
                        valid_add_feed_dict = dict()
                        for addition, add_controller in zip(train_feed_dict_additions, additional_controllers):
                            valid_add_feed_dict[self._pupil_hooks[addition['placeholder']]] = add_controller.get()
                    self._validate(batch_generator_class,
                                   validation_dataset,
                                   train_specs['validation_batch_size'],
                                   train_specs['valid_batch_kwargs'],
                                   training_step=step,
                                   additional_feed_dict=valid_add_feed_dict)
            step += 1
            self.set_in_storage(step=step)
        return step

    @staticmethod
    def _set_controller_name_in_specs(controller_specs, name):
        if isinstance(controller_specs, dict):
            if 'name' not in controller_specs:
                controller_specs['name'] = name

    def _process_abbreviations(self, set_of_kwargs):
        for key, value in set_of_kwargs.items():
            if key == 'stop':
                if isinstance(value, int):
                    set_of_kwargs[key] = {'type': 'limit_steps', 'limit': value}
                self._set_controller_name_in_specs(set_of_kwargs[key], 'stop')
            if key == 'batch_size':
                if isinstance(value, int):
                    set_of_kwargs[key] = {'type': 'fixed', 'value': value}
                self._set_controller_name_in_specs(set_of_kwargs[key], 'batch_size')
            if key == 'num_unrollings':
                if isinstance(value, int):
                    set_of_kwargs[key] = {'type': 'fixed', 'value': value}
                self._set_controller_name_in_specs(set_of_kwargs[key], 'num_unrollings')
            if key == 'checkpoint_steps':
                if isinstance(value, list):
                    set_of_kwargs[key] = {'type': 'true_on_steps', 'steps': value}
                elif isinstance(value, int):
                    set_of_kwargs[key] = {'type': 'true_on_steps', 'steps': [value]}
                else:
                    set_of_kwargs[key] = None
                self._set_controller_name_in_specs(set_of_kwargs[key], 'checkpoint_steps')
            if key == 'learning_rate':
                self._set_controller_name_in_specs(set_of_kwargs[key], 'learning_rate')
            if key == 'debug':
                if isinstance(value, int):
                    set_of_kwargs[key] = {'type': 'true_on_steps', 'step': [value]}
                else:
                    set_of_kwargs[key] = None
                self._set_controller_name_in_specs(set_of_kwargs[key], 'debug')
        if search_in_nested_dictionary(set_of_kwargs, 'summary') is None:
            add_graph_to_summary = search_in_nested_dictionary(set_of_kwargs, 'add_graph_to_summary')
            train_summary_tensors = search_in_nested_dictionary(set_of_kwargs, 'train_summary_tensors')
            if train_summary_tensors is not None:
                if len(train_summary_tensors) > 0:
                    summary_tensors_provided = True
                else:
                    summary_tensors_provided = False
            else:
                summary_tensors_provided = False
            if add_graph_to_summary or summary_tensors_provided:
                set_of_kwargs['summary'] = True
            else:
                set_of_kwargs['summary'] = False
        self._process_datasets_shortcuts(set_of_kwargs)
        self._process_batch_kwargs_shortcuts(set_of_kwargs)
        #print(set_of_kwargs)

    def _process_batch_kwargs_shortcuts(self, set_of_kwargs):
        if 'train_batch_kwargs' not in set_of_kwargs:
            set_of_kwargs['train_batch_kwargs'] = dict()
            if 'num_unrollings' in set_of_kwargs:
                set_of_kwargs['train_batch_kwargs']['num_unrollings'] = set_of_kwargs['num_unrollings']
                if 'valid_batch_kwargs' not in set_of_kwargs:
                    set_of_kwargs['valid_batch_kwargs'] = {'num_unrollings': 1}
                del set_of_kwargs['num_unrollings']
            if 'vocabulary' in set_of_kwargs:
                set_of_kwargs['train_batch_kwargs']['vocabulary'] = set_of_kwargs['vocabulary']
                if 'vocabulary' not in set_of_kwargs['valid_batch_kwargs']:
                    set_of_kwargs['valid_batch_kwargs']['vocabulary'] = set_of_kwargs['vocabulary']
                del set_of_kwargs['vocabulary']

    def _process_datasets_shortcuts(self,
                                    set_of_kwargs):
        taken_names = list(self._datasets.keys())
        train_dataset = self._process_train_dataset_shortcuts(set_of_kwargs, taken_names)
        keys_to_remove = ['train_dataset', 'train_dataset_name', 'train_dataset_text', 'train_dataset_filename']
        for key in keys_to_remove:
            if key in set_of_kwargs:
                del set_of_kwargs[key]
        set_of_kwargs['train_dataset'] = train_dataset
        validation_datasets = self._process_validation_datasets_shortcuts(set_of_kwargs, taken_names)
        keys_to_remove = ['validation_datasets', 'validation_dataset_names',
                          'validation_dataset_texts', 'validation_dataset_filenames']
        for key in keys_to_remove:
            if key in set_of_kwargs:
                del set_of_kwargs[key]
        set_of_kwargs['validation_datasets'] = validation_datasets

    def _process_validation_datasets_shortcuts(self,
                                               set_of_kwargs,
                                               taken_names):
        validation_datasets = list()
        if 'validation_datasets' in set_of_kwargs:
            taken_names.extend(set_of_kwargs['validation_datasets'].keys())
            validation_datasets.extend(set_of_kwargs['validation_datasets'])
        if 'validation_dataset_names' in set_of_kwargs:
            for name in set_of_kwargs['validation_dataset_names']:
                if name not in self._datasets.keys():
                    raise InvalidArgumentError("Wrong value '%s' of variable '%s'\nAllowed values: '%s'" %
                                               (name,
                                                "set_of_kwargs['validation_dataset_names']",
                                                list(self._datasets.keys())))
                validation_datasets.append([self._datasets[name], name])
        if 'validation_dataset_texts' in set_of_kwargs:
            for text in set_of_kwargs['validation_dataset_texts']:
                key, value = self._process_input_text_dataset(text, taken_names)
                taken_names.append(key)
                validation_datasets.append([value, key])
        if 'validation_dataset_filenames' in set_of_kwargs:
            for filename in set_of_kwargs['validation_dataset_filenames']:
                key, value = self._process_dataset_filename(filename)
                taken_names.append(key)
                validation_datasets.append([value, key])
        return validation_datasets

    def _process_train_dataset_shortcuts(self,
                                         set_of_kwargs,
                                         taken_names):
        if 'train_dataset' in set_of_kwargs:
            taken_names.extend(set_of_kwargs['train_dataset'].keys())
            return set_of_kwargs['train_dataset']
        if 'train_dataset_name' in set_of_kwargs:
            if set_of_kwargs['train_dataset_name'] not in self._datasets.keys():
                raise InvalidArgumentError("Wrong value '%s' of variable '%s'\nAllowed values: '%s'" %
                                           (set_of_kwargs['train_dataset_name'], "set_of_kwargs['train_dataset_name']",
                                            list(self._datasets.keys())))
            return [self._datasets[set_of_kwargs['train_dataset_name']], set_of_kwargs['train_dataset_name']]
        if 'train_dataset_text' in set_of_kwargs:
            key, value =  self._process_input_text_dataset(set_of_kwargs['train_dataset_text'], taken_names)
            taken_names.append(key)
            return [value, key]
        if 'train_dataset_filename' in set_of_kwargs:
            key, value = self._process_dataset_filename(set_of_kwargs['train_dataset_filename'])
            taken_names.append(key)
            return [value, key]

    def _process_input_text_dataset(self, input, taken_names):
        idx = 0
        base = 'default_'
        new_key = base + str(idx)
        while new_key in taken_names:
            idx += 1
            new_key = base + str(idx)
        return new_key, input

    def _process_dataset_filename(self, input):
        splitted = input.split('/')
        self._datasets[splitted[-1]] = input
        return splitted[-1], input

    def _parse_1_set_of_kwargs(self,
                               kwargs_to_parse,
                               method_name,
                               repeated_key,
                               only_repeated,
                               old_arguments=None):
        # print('\n\n_parse_1_set_of_kwargs method:\nkwargs_to_parse:\n', kwargs_to_parse, '\nmethod_name:\n',
        #       method_name, '\nrepeated_key:\n', repeated_key, '\nonly_repeated:\n', only_repeated, '\nold_arguments:\n',
        #       old_arguments)
        kwargs_to_parse = construct(kwargs_to_parse)
        self._process_abbreviations(kwargs_to_parse)
        if old_arguments is None:
            if only_repeated:
                tmp = self.get_default_method_parameters(method_name)
                current_arguments = tmp[repeated_key]
            else:
                current_arguments = self.get_default_method_parameters(method_name)
        else:
            current_arguments = construct(old_arguments)

        for key, value in kwargs_to_parse.items():
            paste_into_nested_dictionary(current_arguments, key, value)

        #print('current_arguments:\n', current_arguments)
        return current_arguments

    def _parse_list_of_sets_of_kwargs(self,
                                      list_of_sets,
                                      method_name,
                                      repeated_key):
        # print('\n\n_parse_list_of_sets_of_kwargs method\nlist_of_sets:\n', list_of_sets, '\nmethod_name:\n', method_name,
        #       '\nrepeated_key:\n', repeated_key)
        parsed = self._parse_1_set_of_kwargs(list_of_sets[0],
                                             method_name,
                                             repeated_key,
                                             False)

        parsed[repeated_key] = [parsed[repeated_key]]

        repeated_parsed = parsed[repeated_key][0]
        for kwargs_set in list_of_sets[1:]:
            repeated_parsed = self._parse_1_set_of_kwargs(kwargs_set,
                                                          method_name,
                                                          repeated_key,
                                                          True,
                                                          old_arguments=repeated_parsed)
            parsed[repeated_key].append(repeated_parsed)
        #print('parsed:\n', parsed)
        return parsed

    def _parse_train_method_arguments(self,
                                      train_args,
                                      train_kwargs,
                                      set_passed_parameters_as_default=False):
        """Performs parsing of 'train' and 'train_assistant' method arguments. Optionally updates
        self._pupil_default_training or self._assistant_default_training.
        Args:
            train_args: args passed to train method
            set_passed_parameters_as_default: defines if reset of default parameters is needed
            train_kwargs: kwargs passed to train method
        Returns:
            a dictionary of start parameters (same format as self._default_start)
            a list of dictionaries with all parameters required for launch (each dictionary has the same format as
                self._pupil_default_training or self._assistant_default_training)"""

        #print('\n\n_parse_train_method_arguments method\ntrain_args:', train_args, '\ntrain_kwargs:', train_kwargs)
        if len(train_args) == 0:
            parsed_arguments = self._parse_list_of_sets_of_kwargs([train_kwargs],
                                                                  'train',
                                                                  'run')
        else:
            parsed_arguments = self._parse_list_of_sets_of_kwargs(train_args,
                                                                  'train',
                                                                  'run')

        return parsed_arguments

    def train(self,
              *args,
              start_session=True,
              close_session=True,
              set_passed_parameters_as_default=False,
              **kwargs):
        """The method responsible for model training. User may specify what intermediate results he wishes to
        collect. He may regulate learning process (see arguments). It is also possible to start learning from a check
        point. User may choose if he wishes to limit number of steps
        Args:
            args: A list of arbitrary number of dictionaries which entries are similar to structure of kwargs. It is
                used if user wishes to train model consequently on several datasets. If any dictionary in list contains
                less entries than the previous one, missing entries are taken from previous. If the first doesn't have
                all entries missing entries are filled with default values
            start_session: shows if new session should be created or already opened should be used
            close_session: shows if session should be closed at the end of training
            set_passed_parameters_as_default: if True parameters of launch are saved to self._pupil_default_training.
                If args are provided the first args[0] is used for self._pupil_default_training resetting
            kwargs:
                This argument specifies the learning should be performed. There are many options and it is not
                necessary to provide all kwargs - missing will be filled with default values specified in
                _default_train_method_args atribute
                allow_soft_placement: if True tensorflow is allowed to override device assignments specified by user and
                    put ops on available devices
                gpu_memory: memory fraction tensorflow allowed to allocate. If None all available memory is allocated
                log_device_placement: If True device placements are printed to console
                restore_path: If provided graph will be restored from checkpoint
                save_path: path to directory where all results are saved
                result_types: specifies what types of results should be collected. loss, perplexity, accuracy, bpc are
                    available
                summary: If True summary writing is activated
                add_graph_to_summary: If True graph is added to summary
                batch_generator_class: class of batch generator. It has to have certain methods for correct functioning
                assistant: If meta learning is used for model training it is name of assistant network
                learning_rate: specifications for learning_rate control. If it is a float learning rate will not change
                    while learning. Otherwise it should be a dictionary. Now only exponential decay option is availbale.
                    Below dictionary entries are described
                    exponential decay:
                        type: str 'exponential_decay'
                        init: float, initial learning rate
                        decay: a factor on which learning rate is multiplied every period of steps
                        period: number of steps after which learning rate is being decreased
                additions_to_feed_dict: If your model requires some special placeholders filling (e. g. probability
                    distribution for a stochastic node) it is provided through additions_to_feed_dict. It is a
                    dictionary which keys are tensor aliases in _pupil_hooks attribute and values are dictionaries
                    of the same structure as learning_rate
                stop: specifies when learning should be stopped. It is either an integer (number of steps after which
                    learning is being stopped) or a dictionary of the same structure as learning_rate where you may
                    specify custom way of learning interruption
                train_dataset: A dataset on which model will be trained. It can be a name of dataset provided earlier to
                    Environment constructor or just something what you wish to pass to batch generator (file name, str,
                    etc.)
                batch_size: integer or dictionary of the same type as learning_rate if you wish to somehow change batch
                    size during learning
                train_batch_kwargs: If your batch generator requires some specific arguments they can be provided
                    through this dictionary (for example num_unrollings). This dictionary is used for batch generator
                    construction for training (any of batch generator parameters can be provided as key word args
                    separately if their processing is described in _process_batch_kwargs_shortcut method. Now it is only
                    'vocabulary' and 'num_unrollings')
                checkpoint_steps: list of steps on which checpoints should be created
                debug: step on which tfdbg should be activated. Default is None
                validation_dataset_names: list of dataset names used for validation (datasets have to provided to
                    Environment instance separately. Now only through constructor
                validation_dataset_texts: list of texts (type str) used for validation
                validation_dataset_filenames: file names of datasets used for validation
                  (if validation_dataset_names, validation_dataset_texts, validation_dataset_filenames provided together
                   all of them are used)
                validation_batch_size: batch size for validation
                valid_batch_kwargs: same as train_batch_kwargs
                to_be_collected_while_training: a dictionary with 3 entries (all of them can be provided independently)
                    results_collect_interval: number of steps after which data is collected
                    print_per_collected: every print_per_collected-th point collected with results_collect_interval
                        schedule is printed
                    example_per_print: every example_per_print print examples of model functioning are printed
                        (continuing from random letter, from specified fuse, responding on user specified replicas)
                printed_result_types: what model should print. Default is loss. perplexity, accuracy, bpc are also
                    available
                printed_controllers: if during learning some hyperparameters are changing you may print them to
                    console. Default printed is learning rate
                fuses: specifies fuses from which model should periodically generate text. This option is not
                    available yet
                fuse_tensors: tensor aliases from _pupil_hooks attribute which should be either saved or printed.
                    not available
                replicas: If dialog agent is trained it can be tested with consequently feeding it with few user
                    specified replicas. It can be used to check if agent is capable of dialog context accumulating
                random: NLP agents can be tested on text generating task. It is provided with first character and
                    then tries to generate text. This argument is responsible for specifying how many times it will
                    be performed and specifying length of generated sequences (not available)
                train_tensor_schedule: If user wishes he may print or save any tensor in the graph (not available)
                valid_tensor_schedule: same as train_tensor_schedule"""
        tmp_output = self._parse_train_method_arguments(args,
                                                        kwargs,
                                                        set_passed_parameters_as_default=
                                                        set_passed_parameters_as_default)

        start_specs = tmp_output['start_specs']
        run_specs_set = tmp_output['run']
        batch_generator_class = start_specs['batch_generator_class']
        all_tensor_aliases = self._all_tensor_aliases_from_train_arguments(start_specs, run_specs_set)
        self._create_all_missing_hooks(all_tensor_aliases)

        if start_session:
            self._start_session(start_specs['allow_soft_placement'],
                                start_specs['log_device_placement'],
                                start_specs['gpu_memory'])

        # initializing model
        if start_specs['restore_path'] is not None:
            self._hooks['saver'].restore(self._session, start_specs['restore_path'])
        else:
            self._session.run(tf.global_variables_initializer())

        compute_bpc = 'bpc' in start_specs['result_types']
        self._handler = Handler(self,
                                self._pupil_hooks,
                                'train',
                                start_specs['save_path'],
                                start_specs['result_types'],
                                summary=start_specs['summary'],
                                bpc=compute_bpc,
                                add_graph_to_summary=start_specs['add_graph_to_summary'])

        checkpoints_path = start_specs['save_path'] + '/checkpoints'
        create_path(checkpoints_path)
        init_step = 0
        for run_specs in run_specs_set:
            init_step = self._train(run_specs,
                                    checkpoints_path,
                                    batch_generator_class,
                                    init_step=init_step)
        self._create_checkpoint('final', checkpoints_path)
        self._handler.close()
        if close_session:
            self._close_session()










