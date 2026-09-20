#include "Course.h"

// Implement the required functions here
Course::Course(const string &title, const string &courseCode, int credits) {
    this->title = title;
    this->courseCode = courseCode;
    this->credits = credits;

    this->numOfferings = 0;
    this->courseOfferings = nullptr;
}

Course::~Course() {
    for (int i=0; i<numOfferings; i++)
        delete courseOfferings[i];
    delete[] this->courseOfferings;
    this->courseOfferings = nullptr;
}

CourseOffering* Course::addOffering(Semester semester, int year) {
    CourseOffering * new_course_offering = new CourseOffering(this, semester, year);
    CourseOffering ** courseOfferingArray = new CourseOffering*[numOfferings+1];
    if (numOfferings ==0) {
        courseOfferings = courseOfferingArray;
        courseOfferingArray[0] = new_course_offering;
        numOfferings++;
        return new_course_offering;
    }

    else {
        int i=0;
        int j=0;
        while (i<numOfferings && courseOfferings[i]->compareTo(*new_course_offering) <0) {
            courseOfferingArray[j] = courseOfferings[i];
            i++;
            j++;
        }


        courseOfferingArray[j] = new_course_offering;
        j++;

        while (i<numOfferings)
        {
            courseOfferingArray[j] = courseOfferings[i];
            i++;j++;
        }
        
        delete [] this->courseOfferings;
        this->courseOfferings = courseOfferingArray;
        this->numOfferings ++;
        return new_course_offering;
    }
}

bool Course::hasOffering(Semester semester, int year) const {
    for (int i=0; i<this->numOfferings; i++) {
        if (this->courseOfferings[i]->sameSemester(semester, year)) return true;
    }
    return false;
}
CourseOffering* Course::getOffering(Semester semester, int year) const {
    for (int i=0; i<this->numOfferings; i++) {
        if (this->courseOfferings[i]->sameSemester(semester, year)) return this->courseOfferings[i];
    }
    return nullptr;
};

int Course::compareTo(const Course &other) const{
    return (this->courseCode.compare(other.courseCode));
};





// The following functions are implemented for you.
// DO NOT MODIFY THE LINES BELOW.
void Course::printInfo() const {
    cout << "Course " << courseCode << " - " << title << " (" << credits << " credit" << (credits == 1 ? "" : "s") << ")" << endl;
}

void Course::printOfferings() const {
    printInfo();
    if (numOfferings)
        for (int i = 0; i < numOfferings; i++)
            courseOfferings[i]->printOffering();
    else
        cout << "No Offerings." << endl;
}
