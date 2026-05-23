module.exports = {

    startsWith: function(val, str) {
        if (val == null) return false;
        return String(val).startsWith(str);
    },

    endsWith: function(val, str) {
        if (val == null) return false;
        return String(val).endsWith(str);
    },

    contains: function(val, str) {
        if (val == null) return false;
        if (Array.isArray(val)) return val.includes(str);
        return String(val).includes(str);
    },

    between: function(val, min, max) {
        return val >= min && val <= max;
    },

    inRange: function(val, min, max) {
        val = Number(val);
        min = Number(min);
        max = Number(max);

        return val >= min && val <= max;
    },

    inArray: function(val, arr) {
        if (!Array.isArray(arr)) return false;
        return arr.includes(val);
    },

};