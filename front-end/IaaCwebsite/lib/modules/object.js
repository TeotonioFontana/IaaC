const { clone } = require('../core/util');

// Add new property to an object (does not override existing properties)
exports.addProperty = function(options) {
  let obj = this.parseRequired(options.object, 'object', 'object.addProperty: object is required.');
  let prop = this.parseRequired(options.prop, 'string', 'object.addProperty: property is required.');
  let value = this.parseOptional(options.value, '*', null);

  let output = clone(obj);

  if (output[prop] == null) {
    output[prop] = value;
  }

  return output;
};

// Remove a property from an object
exports.removeProperty = function(options) {
  let obj = this.parseRequired(options.object, 'object', 'object.removeProperty: object is required.');
  let prop = this.parseRequired(options.prop, 'string', 'object.removeProperty: property is required.');

  let output = clone(obj);

  delete output[prop];

  return output;
};

// Set a property on an object (overrides existing properties)
exports.setProperty = function(options) {
  let obj = this.parseRequired(options.object, 'object', 'object.setProperty: object is required.');
  let prop = this.parseRequired(options.prop, 'string', 'object.setProperty: property is required.');

  // Check if value property exists (allow null values)
  if (!('value' in options)) {
    throw new Error('object.setProperty: value is required.');
  }

  let value = options.value;
  let output = clone(obj);

  output[prop] = value;

  return output;
};
